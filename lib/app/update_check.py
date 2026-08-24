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
import re
import threading
import urllib.error
import urllib.request
from typing import Callable, Optional

from app.version import __version__

RELEASES_API = "https://api.github.com/repos/mhyde777/dnd_app/releases/latest"
RELEASES_PAGE = "https://github.com/mhyde777/dnd_app/releases/latest"

_TIMEOUT_SECONDS = 6


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


def fetch_latest_version(url: str = RELEASES_API) -> Optional[str]:
    """The latest release tag, or None if it can't be determined."""
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

    tag = payload.get("tag_name") or payload.get("name")
    return str(tag) if tag else None


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
