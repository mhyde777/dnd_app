"""Verification, archive safety, and installing a version beside a running one.

No network and no PyInstaller: these cover the logic that decides whether a
downloaded build is safe to unpack and where it lands. The end-to-end check
with two real packaged builds is manual — see docs/auto-update.md.
"""
import hashlib
import os
from datetime import datetime, timezone
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


def test_prune_keeps_whatever_current_points_at(install, tmp_path):
    """Reverting sets `current` to an older build; pruning must not delete it."""
    for version in ("0.1.0", "0.3.0", "0.4.0", "0.5.0"):
        os.makedirs(install.version_dir(version), exist_ok=True)
    # Running 0.5.0, but reverted: the next launch is meant to be 0.1.0.
    running = install_layout.Layout(root=install.root, version="0.5.0")
    install_layout.write_current(running, "0.1.0")

    update_install.prune_versions(running, keep=2)
    left = running.installed_versions()
    assert "0.1.0" in left, "the version `current` names must survive pruning"
    assert "0.5.0" in left, "the running version must survive pruning"


# ---- history and deferred pruning -------------------------------------------

@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Point app.settings at a scratch file for tests that write to it."""
    from app import settings

    monkeypatch.setattr(settings, "_cache", None, raising=False)
    monkeypatch.setattr(settings, "settings_path", lambda: str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "config_dir", lambda: str(tmp_path), raising=False)
    yield settings
    settings._cache = None


def _start(install, version):
    """Simulate `version` starting successfully."""
    layout = install_layout.Layout(root=install.root, version=version)
    install_layout.write_current(layout, version)
    open(layout.launching_file, "w").write(version + "\n")
    install_layout.clear_launching(layout)
    return layout


def test_a_successful_start_records_history(install, isolated_settings):
    for version in ("0.3.0", "0.4.0"):
        os.makedirs(install.version_dir(version), exist_ok=True)
    running = _start(install, "0.4.0")

    assert not os.path.exists(running.launching_file)
    assert [e["version"] for e in install_layout.version_history()] == ["0.4.0"]


def test_a_superseded_version_gets_a_reprieve_before_deletion(install, isolated_settings):
    """The build being replaced is not deleted the moment the new one starts.

    A version that starts cleanly and only then turns out to be wrong still has
    somewhere to go back to.
    """
    for version in ("0.2.5", "0.3.0", "0.4.0"):
        os.makedirs(install.version_dir(version), exist_ok=True)
    running = _start(install, "0.4.0")

    # keep=2 puts 0.2.5 outside the window, but it is on probation, not gone.
    assert "0.2.5" in running.installed_versions()
    due = install_layout.retire_at("0.2.5")
    assert due is not None, "it should have been given a retirement time"
    remaining = (due - datetime.now(timezone.utc)).total_seconds() / 60
    assert 0 < remaining <= install_layout.DEFAULT_GRACE_MINUTES


def test_the_reprieve_expires(install, isolated_settings):
    for version in ("0.2.5", "0.3.0", "0.4.0"):
        os.makedirs(install.version_dir(version), exist_ok=True)
    isolated_settings.set(install_layout.GRACE_KEY, 0)   # no probation
    running = _start(install, "0.4.0")

    assert running.installed_versions() == ["0.3.0", "0.4.0"]


def test_choosing_a_version_again_cancels_its_retirement(install, isolated_settings):
    for version in ("0.2.5", "0.3.0", "0.4.0"):
        os.makedirs(install.version_dir(version), exist_ok=True)
    _start(install, "0.4.0")
    assert install_layout.retire_at("0.2.5") is not None

    install_layout.cancel_retirement("0.2.5")
    assert install_layout.retire_at("0.2.5") is None


def test_history_survives_the_version_being_pruned(install, isolated_settings):
    """The point of the history: a version can leave disk and still be offered."""
    isolated_settings.set(install_layout.GRACE_KEY, 0)
    for version in ("0.3.0", "0.4.0", "0.5.0"):
        os.makedirs(install.version_dir(version), exist_ok=True)

    for version in ("0.3.0", "0.4.0", "0.5.0"):
        _start(install, version)

    remembered = [e["version"] for e in install_layout.version_history()]
    on_disk = install_layout.Layout(root=install.root, version="0.5.0").installed_versions()

    assert "0.3.0" in remembered
    assert "0.3.0" not in on_disk


def test_keep_versions_is_never_below_one(isolated_settings):
    isolated_settings.set(install_layout.KEEP_VERSIONS_KEY, 0)
    assert install_layout.keep_versions() >= 1
    isolated_settings.set(install_layout.KEEP_VERSIONS_KEY, "nonsense")
    assert install_layout.keep_versions() == install_layout.DEFAULT_KEEP_VERSIONS
