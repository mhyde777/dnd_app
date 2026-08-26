# lib/app/update_install.py
"""
Verify a downloaded release and unpack it, without trusting its contents.

Nothing here touches the running installation. Unpacking goes to a directory
the caller chooses, and install_layout.py decides where that is -- the whole
scheme depends on a new version landing *beside* the running one rather than
on top of it, which is what makes updating a running app possible at all.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import zipfile
from typing import Callable, Optional

_HASH_CHUNK = 1024 * 1024


class UnsafeArchive(Exception):
    """The archive tried to write outside the directory it was given."""


def sha256(path: str, on_progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Hex digest of a file, read in chunks so a 200MB build doesn't blow up."""
    total = os.path.getsize(path)
    done = 0
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if on_progress is not None:
                on_progress(done, total)
    return digest.hexdigest()


def parse_sha256sums(text: str) -> dict:
    """`sha256sum` output to {filename: digest}.

    Accepts both the plain and the binary ('*name') forms, and ignores
    anything that isn't a digest/name pair so a stray header line in a
    hand-written SHA256SUMS doesn't fail the whole file.
    """
    sums = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        digest, name = parts
        if len(digest) != 64:
            continue
        try:
            int(digest, 16)
        except ValueError:
            continue
        sums[name.lstrip("*")] = digest.lower()
    return sums


def expected_digest(asset: dict, sums_text: str = "") -> Optional[str]:
    """The digest to check an asset against, or None if we have nothing.

    GitHub returns `digest` ("sha256:...") on newer releases; a SHA256SUMS file
    published alongside covers the ones it doesn't. Without either there is
    nothing to compare to, and the caller has to decide whether to proceed.
    """
    raw = str(asset.get("digest") or "")
    if raw.lower().startswith("sha256:"):
        candidate = raw.split(":", 1)[1].strip().lower()
        if len(candidate) == 64:
            return candidate
    return parse_sha256sums(sums_text).get(str(asset.get("name") or ""))


def verify(path: str, digest: str) -> bool:
    return bool(digest) and sha256(path) == digest.lower()


# ---- Extraction -------------------------------------------------------------

def _is_within(base: str, target: str) -> bool:
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def _safe_members(archive, names, dest: str):
    """Reject anything that would escape `dest` before a single byte is written.

    An absolute path, a `..` component or a symlink pointing outside turns an
    unpack into an arbitrary file write. Checked up front rather than per-file
    so a malicious archive cannot half-extract.
    """
    for name in names:
        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
            raise UnsafeArchive(f"archive member escapes the target: {name}")
        if not _is_within(dest, os.path.join(dest, name)):
            raise UnsafeArchive(f"archive member escapes the target: {name}")


def extract(archive: str, dest: str) -> str:
    """Unpack a .tar.gz or .zip into `dest`, which must not already exist."""
    if os.path.exists(dest):
        raise FileExistsError(dest)
    os.makedirs(dest, exist_ok=True)

    try:
        if archive.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive, "r:gz") as tar:
                members = tar.getmembers()
                _safe_members(tar, [m.name for m in members], dest)
                for member in members:
                    # A symlink or hardlink can point outside even when its own
                    # name is innocent.
                    if member.issym() or member.islnk():
                        target = os.path.join(dest, os.path.dirname(member.name),
                                              member.linkname)
                        if os.path.isabs(member.linkname) or not _is_within(dest, target):
                            raise UnsafeArchive(f"link escapes the target: {member.name}")
                tar.extractall(dest)
        elif archive.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                _safe_members(zf, zf.namelist(), dest)
                zf.extractall(dest)
                # Zip drops the executable bit, so the app binary would unpack
                # unrunnable on Linux and macOS.
                for info in zf.infolist():
                    mode = (info.external_attr >> 16) & 0o777
                    if mode:
                        path = os.path.join(dest, info.filename)
                        if os.path.exists(path):
                            os.chmod(path, mode)
        else:
            raise ValueError(f"unsupported archive type: {archive}")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def find_payload_root(unpacked: str, marker: str) -> Optional[str]:
    """The directory inside an unpacked release that holds the app itself.

    Release tarballs wrap everything in one `combat-tracker-<ver>-<plat>/`
    directory, so the payload is one level down -- but not always, and guessing
    wrong installs a version whose binary isn't where the launcher looks.
    """
    if os.path.isdir(os.path.join(unpacked, marker)):
        return unpacked
    entries = [
        os.path.join(unpacked, name)
        for name in os.listdir(unpacked)
        if os.path.isdir(os.path.join(unpacked, name))
    ]
    for entry in entries:
        if os.path.isdir(os.path.join(entry, marker)):
            return entry
    return None


# ---- Installing a version beside the running one ----------------------------

def find_app_payload(unpacked: str, binary: str, depth: int = 3) -> Optional[str]:
    """The directory holding the app binary inside an unpacked release.

    Release archives wrap the build in a versioned directory, and the build
    itself sits one level further down, so this searches rather than assuming.
    Installing a directory whose binary is not where the launcher looks would
    produce a version that can never start.
    """
    for root, dirs, files in os.walk(unpacked):
        if binary in files and os.path.isfile(os.path.join(root, binary)):
            return root
        if os.path.relpath(root, unpacked).count(os.sep) >= depth:
            dirs[:] = []
    return None


def install_release(archive: str, version: str, layout, binary: str) -> str:
    """Unpack `archive` into versions/<version>/ and return that path.

    Extraction goes to a sibling `.incoming` directory and is renamed into
    place only once it is complete and the binary has been found. A rename
    within the same directory is as close to atomic as this gets: the launcher
    can never catch a half-written version, because a half-written one is not
    yet called by its version name.
    """
    target = layout.version_dir(version)
    if os.path.isdir(target):
        return target

    os.makedirs(layout.versions_dir, exist_ok=True)
    staging = target + ".incoming"
    shutil.rmtree(staging, ignore_errors=True)

    try:
        extract(archive, staging)
        payload = find_app_payload(staging, binary)
        if payload is None:
            raise FileNotFoundError(
                f"the downloaded build has no {binary} in it"
            )
        os.replace(payload, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)
        raise

    shutil.rmtree(staging, ignore_errors=True)
    try:
        os.chmod(os.path.join(target, binary), 0o755)
    except OSError:
        pass
    return target


def prune_versions(layout, keep: int = 2, protect: Optional[list] = None) -> list:
    """Delete all but the newest `keep` versions. Returns what was removed.

    Never removes the running version or whatever `current` points at, however
    old they are -- disk is cheaper than deleting the build someone is using.
    """
    from app.install_layout import read_current
    from app.update_check import _parse  # the one version-ordering rule

    protected = set(protect or [])
    protected.add(layout.version)
    # And whatever `current` names, which is not always the running version:
    # after switching back to an older build, the one about to run next is
    # older than the one running now, and pruning would delete it.
    selected = read_current(layout)
    if selected:
        protected.add(selected)
    versions = sorted(layout.installed_versions(), key=_parse, reverse=True)

    removed = []
    for version in versions[keep:]:
        if version in protected:
            continue
        path = layout.version_dir(version)
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.isdir(path):
            removed.append(version)
    return removed


def relaunch(layout, extra_args: Optional[list] = None) -> None:
    """Start the launcher, telling it to wait for this process to exit.

    Waiting matters: two copies overlapping would both hold the log and both
    write settings on close, and the one that quit *second* would win -- so the
    old version could silently overwrite what the new one just saved.
    """
    command = [layout.launcher, "--wait-pid", str(os.getpid())]
    if extra_args:
        command += ["--"] + list(extra_args)

    kwargs = {"close_fds": True}
    if os.name == "posix":
        kwargs["start_new_session"] = True      # survive this process's exit
    else:
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(command, **kwargs)
