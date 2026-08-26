"""Verification, archive safety, and installing a version beside a running one.

No network and no PyInstaller: these cover the logic that decides whether a
downloaded build is safe to unpack and where it lands. The end-to-end check
with two real packaged builds is manual — see docs/auto-update.md.
"""
import hashlib
import os
import subprocess
import sys
import tarfile
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib"))

from app import install_layout, update_install  # noqa: E402


def make_build(root, version, binary="combat_tracker"):
    """A directory shaped like a packaged build."""
    stage = root / f"combat-tracker-{version}-linux-x86_64"
    payload = stage / "versions" / version
    payload.mkdir(parents=True)
    (payload / binary).write_text("#!/bin/sh\necho app\n")
    (payload / "_internal").mkdir()
    (payload / "_internal" / "data.bin").write_text(version)
    return stage


def make_tarball(tmp_path, stage):
    archive = tmp_path / f"{stage.name}.tar.gz"
    subprocess.run(
        ["tar", "-C", str(stage.parent), "-czf", str(archive), stage.name], check=True
    )
    return archive


# ---- checksums --------------------------------------------------------------

def test_sha256_matches_hashlib(tmp_path):
    target = tmp_path / "blob"
    target.write_bytes(b"hello world")
    assert update_install.sha256(str(target)) == hashlib.sha256(b"hello world").hexdigest()


def test_parse_sha256sums_takes_both_forms_and_ignores_junk():
    digest = "a" * 64
    parsed = update_install.parse_sha256sums(
        f"{digest}  plain.tar.gz\n{digest} *binary.zip\nnot a checksum line\n"
    )
    assert parsed == {"plain.tar.gz": digest, "binary.zip": digest}


def test_expected_digest_prefers_the_release_field():
    digest = "b" * 64
    asset = {"name": "build.tar.gz", "digest": f"sha256:{digest}"}
    assert update_install.expected_digest(asset, "") == digest


def test_expected_digest_falls_back_to_sha256sums():
    digest = "c" * 64
    asset = {"name": "build.tar.gz"}
    assert update_install.expected_digest(asset, f"{digest}  build.tar.gz\n") == digest


def test_expected_digest_is_none_when_nothing_is_published():
    assert update_install.expected_digest({"name": "build.tar.gz"}, "") is None


def test_verify_rejects_a_mismatch(tmp_path):
    target = tmp_path / "blob"
    target.write_bytes(b"payload")
    assert update_install.verify(str(target), update_install.sha256(str(target)))
    assert not update_install.verify(str(target), "0" * 64)


# ---- archives that try to escape --------------------------------------------

def _tar_with_member(path, name):
    payload = path.parent / "payload.txt"
    payload.write_text("x")
    with tarfile.open(path, "w:gz") as tar:
        info = tar.gettarinfo(str(payload), arcname=name)
        info.name = name          # gettarinfo strips a leading /; put it back
        with open(payload, "rb") as handle:
            tar.addfile(info, handle)


@pytest.mark.parametrize("name", ["../escaped.txt", "/etc/passwd", "a/../../b.txt"])
def test_extract_refuses_members_outside_the_target(tmp_path, name):
    archive = tmp_path / "evil.tar.gz"
    _tar_with_member(archive, name)
    dest = tmp_path / "out"
    with pytest.raises(update_install.UnsafeArchive):
        update_install.extract(str(archive), str(dest))
    assert not dest.exists(), "a rejected archive must not leave a directory behind"


def test_extract_refuses_a_symlink_pointing_outside(tmp_path):
    archive = tmp_path / "link.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("innocent/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../../../etc/passwd"
        tar.addfile(info)
    with pytest.raises(update_install.UnsafeArchive):
        update_install.extract(str(archive), str(tmp_path / "out"))


def test_extract_restores_the_executable_bit_from_a_zip(tmp_path):
    archive = tmp_path / "build.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("versions/1.0.0/combat_tracker")
        info.external_attr = 0o755 << 16
        zf.writestr(info, "#!/bin/sh\n")
    out = update_install.extract(str(archive), str(tmp_path / "out"))
    assert os.access(os.path.join(out, "versions", "1.0.0", "combat_tracker"), os.X_OK)


# ---- installing beside the running version ----------------------------------

@pytest.fixture
def install(tmp_path):
    """A versioned installation with 0.2.0 in it."""
    root = tmp_path / "install"
    (root / "versions" / "0.2.0").mkdir(parents=True)
    (root / "versions" / "0.2.0" / "combat_tracker").write_text("#!/bin/sh\n")
    (root / "combat-tracker").write_text("#!/bin/sh\n")
    (root / "current").write_text("0.2.0\n")
    return install_layout.Layout(root=str(root), version="0.2.0")


def test_install_release_adds_a_version_without_touching_the_running_one(tmp_path, install):
    archive = make_tarball(tmp_path, make_build(tmp_path, "0.3.0"))
    target = update_install.install_release(str(archive), "0.3.0", install, "combat_tracker")

    assert os.path.isdir(target)
    assert os.path.isfile(os.path.join(target, "combat_tracker"))
    assert install.installed_versions() == ["0.2.0", "0.3.0"]
    assert os.path.isfile(os.path.join(install.version_dir("0.2.0"), "combat_tracker"))


def test_install_release_leaves_nothing_behind_when_the_archive_is_junk(tmp_path, install):
    archive = tmp_path / "broken.tar.gz"
    archive.write_bytes(b"not a tarball")
    with pytest.raises(Exception):
        update_install.install_release(str(archive), "0.3.0", install, "combat_tracker")
    assert not os.path.exists(install.version_dir("0.3.0"))
    assert install.installed_versions() == ["0.2.0"]


def test_install_release_rejects_an_archive_with_no_app_binary(tmp_path, install):
    stage = tmp_path / "combat-tracker-0.3.0-linux-x86_64"
    (stage / "docs").mkdir(parents=True)
    (stage / "docs" / "readme.txt").write_text("x")
    archive = make_tarball(tmp_path, stage)
    with pytest.raises(FileNotFoundError):
        update_install.install_release(str(archive), "0.3.0", install, "combat_tracker")
    assert not os.path.exists(install.version_dir("0.3.0"))


def test_no_incoming_directory_survives_a_successful_install(tmp_path, install):
    archive = make_tarball(tmp_path, make_build(tmp_path, "0.3.0"))
    update_install.install_release(str(archive), "0.3.0", install, "combat_tracker")
    leftovers = [n for n in os.listdir(install.versions_dir) if n.endswith(".incoming")]
    assert leftovers == []


def test_prune_keeps_the_running_version_however_old(install):
    for version in ("0.1.0", "0.1.5", "0.3.0", "0.4.0"):
        os.makedirs(install.version_dir(version), exist_ok=True)
    update_install.prune_versions(install, keep=2)
    left = install.installed_versions()
    assert "0.2.0" in left, "the running version must never be pruned"
    assert "0.4.0" in left and "0.3.0" in left
    assert "0.1.0" not in left


# ---- layout detection -------------------------------------------------------

def test_detect_recognises_a_versioned_install(tmp_path):
    here = tmp_path / "root" / "versions" / "1.2.3"
    here.mkdir(parents=True)
    layout = install_layout.detect(str(here))
    assert layout is not None
    assert layout.version == "1.2.3"
    assert layout.root == str(tmp_path / "root")


def test_detect_rejects_a_flat_install(tmp_path):
    here = tmp_path / "root"
    here.mkdir()
    assert install_layout.detect(str(here)) is None


def test_write_current_is_atomic_and_readable(install):
    install_layout.write_current(install, "0.9.9")
    assert install_layout.read_current(install) == "0.9.9"
    assert not os.path.exists(install.current_file + ".tmp")


def test_can_self_update_refuses_a_source_checkout():
    possible, reason = install_layout.can_self_update()
    assert possible is False
    assert "source checkout" in reason
