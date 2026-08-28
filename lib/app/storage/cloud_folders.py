"""
Finding the folders Dropbox, Google Drive, OneDrive and iCloud keep in sync.

Every one of these services runs a background client that presents itself to
the operating system as a plain directory. That is why they are supported as
storage providers without a single line of OAuth: the app writes JSON into a
directory, and their client does the rest. It works offline, survives the app
being closed mid-upload, and leaves the library as files the user can open,
back up and read without this app existing.

What is actually hard is *finding* the directory, because none of them agree on
where it goes. Detection is best-effort and never load-bearing -- when it comes
up empty the provider is still offered, with an empty path for the user to
Browse to. A wrong guess is worse than no guess, so each probe below looks for
something the service itself wrote (Dropbox's `info.json`, OneDrive's
environment variable) before falling back to a conventional path.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import dataclass
from typing import List, Optional

#: Appended to a detected sync root, so the library is one tidy folder rather
#: than encounters loose at the top of somebody's Dropbox.
LIBRARY_DIR_NAME = "DnD Tracker"


@dataclass(frozen=True)
class CloudFolder:
    provider_id: str
    root: str          # the sync root, e.g. /home/alice/Dropbox
    detected: bool     # False when this is a convention, not a discovery

    @property
    def library_path(self) -> str:
        return os.path.join(self.root, LIBRARY_DIR_NAME)


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


def _first_existing(candidates: List[str]) -> Optional[str]:
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


def _first_glob(patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            if os.path.isdir(path):
                return path
    return None


def detect_dropbox() -> Optional[str]:
    """Dropbox writes its own location to info.json -- ask it, don't guess.

    People move the Dropbox folder, and on Windows it is routinely on a
    different drive from the user profile, so `~/Dropbox` is a poor guess.
    """
    candidates = [
        _home(".dropbox", "info.json"),
        os.path.join(os.getenv("LOCALAPPDATA", ""), "Dropbox", "info.json"),
        os.path.join(os.getenv("APPDATA", ""), "Dropbox", "info.json"),
    ]
    for info_path in candidates:
        if not info_path or not os.path.isfile(info_path):
            continue
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        # "personal" and "business" are the two account types; either will do.
        for account in ("personal", "business"):
            path = (info.get(account) or {}).get("path")
            if path and os.path.isdir(path):
                return path
    return _first_existing([_home("Dropbox")])


def detect_onedrive() -> Optional[str]:
    """OneDrive exports its path as an environment variable on Windows."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        path = os.getenv(var, "").strip()
        if path and os.path.isdir(path):
            return path
    found = _first_glob([
        "~/Library/CloudStorage/OneDrive-Personal",
        "~/Library/CloudStorage/OneDrive-*",
    ])
    return found or _first_existing([_home("OneDrive")])


def detect_google_drive() -> Optional[str]:
    """Google Drive for Desktop, which is inconsistent across platforms.

    macOS gets a predictable CloudStorage mount. Windows mounts a virtual
    drive whose letter the user chooses, so the drive roots are probed. Linux
    has no official client at all, only third-party mounts at conventional
    paths.
    """
    found = _first_glob([
        "~/Library/CloudStorage/GoogleDrive-*/My Drive",
        "~/Google Drive/My Drive",
    ])
    if found:
        return found

    if sys.platform == "win32":
        for letter in "GHIJKLMNOPQRSTUVWXYZ":
            candidate = f"{letter}:\\My Drive"
            if os.path.isdir(candidate):
                return candidate

    return _first_existing([
        _home("Google Drive"),
        _home("GoogleDrive"),
        _home("google-drive"),
    ])


def detect_icloud() -> Optional[str]:
    return _first_existing([
        _home("Library", "Mobile Documents", "com~apple~CloudDocs"),
        _home("iCloudDrive"),
    ])


_DETECTORS = {
    "dropbox": detect_dropbox,
    "google_drive": detect_google_drive,
    "onedrive": detect_onedrive,
    "icloud": detect_icloud,
}

# Where each service would put its folder if it were installed. Used only to
# fill the Browse box with a sensible starting point when detection fails.
_CONVENTIONS = {
    "dropbox": lambda: _home("Dropbox"),
    "google_drive": lambda: _home("Google Drive"),
    "onedrive": lambda: _home("OneDrive"),
    "icloud": lambda: _home("iCloudDrive"),
}


def detect(provider_id: str) -> Optional[CloudFolder]:
    """The sync root for one service, or None if it is not one we detect."""
    detector = _DETECTORS.get(provider_id)
    if detector is None:
        return None
    try:
        root = detector()
    except Exception:
        # Detection is a convenience. A permissions error probing someone's
        # home directory must not stop the settings dialog from opening.
        root = None
    if root:
        return CloudFolder(provider_id, root, detected=True)
    convention = _CONVENTIONS.get(provider_id)
    return CloudFolder(provider_id, convention() if convention else "", detected=False)


def suggested_path(provider_id: str) -> str:
    """The library folder to offer for `provider_id`, or "" if unknown."""
    folder = detect(provider_id)
    return folder.library_path if folder and folder.root else ""


def is_detected(provider_id: str) -> bool:
    folder = detect(provider_id)
    return bool(folder and folder.detected)
