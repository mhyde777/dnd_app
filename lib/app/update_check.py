"""
Check whether a newer release exists, and say so. Nothing more.

Deliberately not an auto-updater. Swapping a running executable needs a helper
process on Windows, and downloading and executing new code from an unsigned
build is a bad trade for a small user base. This tells the user a release
exists and gets out of the way; they download and replace the folder, and
their data is untouched because it lives in the config directory.

The check runs on a background thread and fails silently. Someone playing
offline should never see a network error about updates.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import threading
import urllib.error
import urllib.request
from typing import Callable, Optional

from app.version import __version__

RELEASES_API = "https://api.github.com/repos/mhyde777/dnd_app/releases/latest"
RELEASES_PAGE = "https://github.com/mhyde777/dnd_app/releases/latest"

_TIMEOUT_SECONDS = 6
_CHUNK_BYTES = 64 * 1024
# A checksum list is a few hundred bytes; the cap is just a sanity bound.
_MAX_TEXT_BYTES = 256 * 1024


_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[-+](.+))?$")


def _parse(version: str) -> tuple:
    """Version string to a comparable tuple.

    A pre-release sorts *below* its release -- 0.2.0-rc1 < 0.2.0 -- so the
    flag has to be a separate component. Comparing element-by-element instead
    would make the longer tuple win and offer people release candidates as
    though they were upgrades. Numeric parts are padded so 0.2 == 0.2.0.
    """
    cleaned = (version or "").strip().lstrip("vV")
    match = _VERSION_RE.match(cleaned)
    if not match:
        return ((0, 0, 0, 0), 0, ())

    numbers = [int(p) for p in match.group(1).split(".")][:4]
    numbers += [0] * (4 - len(numbers))
    pre = match.group(2)
    # 1 for a plain release, 0 for a pre-release: releases win ties.
    return (tuple(numbers), 0 if pre else 1, tuple(pre.split(".")) if pre else ())


def is_newer(candidate: str, current: str = __version__) -> bool:
    return _parse(candidate) > _parse(current)


def fetch_latest_release(url: str = RELEASES_API) -> Optional[dict]:
    """The whole latest-release payload, or None if it can't be fetched.

    404 is the normal answer for a repo with no published releases -- a tag on
    its own is not one -- and HTTPError is a URLError, so that lands in the
    same silent path as being offline.
    """
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"dnd-combat-tracker/{__version__}",
            },
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def fetch_latest_version(url: str = RELEASES_API) -> Optional[str]:
    """The latest release tag, or None if it can't be determined."""
    payload = fetch_latest_release(url)
    if payload is None:
        return None
    tag = payload.get("tag_name") or payload.get("name")
    return str(tag) if tag else None


# ---- Picking the right download -------------------------------------------
# Asset names come from package.sh / package_WIN.sh:
#   combat-tracker-<version>-linux-<arch>.tar.gz
#   combat-tracker-<version>-windows-x64.zip
#   combat-tracker-<version>-macos-<arch>.zip   (documented, not yet built)

_PLATFORM_TOKENS = {
    "linux": ("linux",),
    "win32": ("windows", "win64", "win"),
    "darwin": ("macos", "darwin", "osx"),
}

_ARCH_ALIASES = {
    "x86_64": ("x86_64", "amd64", "x64"),
    "amd64":  ("x86_64", "amd64", "x64"),
    "aarch64": ("aarch64", "arm64"),
    "arm64":  ("aarch64", "arm64"),
}


def asset_for_platform(release: Optional[dict]) -> Optional[dict]:
    """The asset this machine should download, or None if the release has none.

    Prefers a name matching both the platform and this machine's architecture,
    and settles for the platform alone -- a Windows build is named win64 with
    no arch of its own. Returning None is normal: a release published without
    artifacts attached has only GitHub's source zips, which are not runnable.
    """
    assets = (release or {}).get("assets") or []
    if not assets:
        return None

    tokens = _PLATFORM_TOKENS.get(sys.platform, (sys.platform,))
    arches = _ARCH_ALIASES.get(platform.machine().lower(), (platform.machine().lower(),))

    platform_matches = [
        a for a in assets
        if isinstance(a, dict)
        and any(t in str(a.get("name", "")).lower() for t in tokens)
    ]
    if not platform_matches:
        return None

    for asset in platform_matches:
        name = str(asset.get("name", "")).lower()
        if any(arch in name for arch in arches):
            return asset
    return platform_matches[0]


def download_asset(
    asset: dict,
    dest_dir: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    """Stream one release asset to `dest_dir`. Returns the path, or None.

    Downloads to a .part file and renames on success, so an interrupted or
    cancelled download can never leave something that looks like a usable
    build sitting in the user's Downloads folder.
    """
    url = asset.get("browser_download_url")
    name = asset.get("name")
    if not url or not name:
        return None

    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, str(name))
    partial = final + ".part"
    total = int(asset.get("size") or 0)

    request = urllib.request.Request(
        url, headers={"User-Agent": f"dnd-combat-tracker/{__version__}"}
    )
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            length = response.headers.get("Content-Length")
            if length and not total:
                total = int(length)
            with open(partial, "wb") as handle:
                while True:
                    if cancelled is not None and cancelled():
                        raise _Cancelled()
                    chunk = response.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    if on_progress is not None:
                        on_progress(received, total)
    except _Cancelled:
        _discard(partial)
        return None
    except (urllib.error.URLError, OSError, ValueError):
        _discard(partial)
        raise

    os.replace(partial, final)
    return final


class _Cancelled(Exception):
    """The user pressed Cancel; not an error worth reporting."""


def _discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def fetch_text(url: str) -> str:
    """Fetch a small text asset (a SHA256SUMS file). Empty string on failure."""
    if not url:
        return ""
    request = urllib.request.Request(
        url, headers={"User-Agent": f"dnd-combat-tracker/{__version__}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.read(_MAX_TEXT_BYTES).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def downloads_dir() -> str:
    """Where to put the downloaded build."""
    candidate = os.path.join(os.path.expanduser("~"), "Downloads")
    return candidate if os.path.isdir(candidate) else os.path.expanduser("~")


def check_in_background(
    on_update: Callable[[str], None],
    url: str = RELEASES_API,
) -> threading.Thread:
    """Call `on_update(version)` if a newer release exists. Never raises.

    The callback lands on a worker thread, so a Qt caller must marshal it back
    to the GUI thread before touching widgets.
    """

    def run() -> None:
        latest = fetch_latest_version(url)
        if latest and is_newer(latest):
            try:
                on_update(latest)
            except Exception:
                pass

    thread = threading.Thread(target=run, name="update-check", daemon=True)
    thread.start()
    return thread


def latest_in_background(on_result: Callable[[Optional[dict]], None]) -> threading.Thread:
    """Fetch the latest release and always call back, with None when there is none.

    check_in_background() stays quiet unless there is something newer, which is
    right at startup. A menu item the user just clicked has to answer either
    way, or it looks broken.
    """

    def run() -> None:
        try:
            on_result(fetch_latest_release())
        except Exception:
            pass

    thread = threading.Thread(target=run, name="update-check-manual", daemon=True)
    thread.start()
    return thread
