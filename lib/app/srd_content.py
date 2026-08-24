"""
Access to the SRD 5.2.1 library bundled with the application.

The payload is a directory of JSON files generated once from the official
CC-BY-4.0 PDF by `scripts/extract_srd.py` and committed; see LICENSE-SRD.md
for the attribution this carries.

It ships inside the PyInstaller bundle, so the location differs between a
frozen build (`sys._MEIPASS/srd_content`) and a source checkout (the repo
root). Everything here degrades quietly when the payload is absent -- a source
checkout without it is a normal state, not an error.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterator, Optional

CATEGORIES = ("statblocks", "spells")

# Category -> (storage list method, storage save method), so callers can treat
# both the local and remote backends through one interface.
STORAGE_METHODS = {
    "statblocks": ("list_statblock_keys", "save_statblock"),
    "spells": ("list_spell_keys", "save_spell"),
}

_DIR_NAME = "srd_content"


def content_dir() -> Optional[Path]:
    """Where the bundled library lives, or None if this build has none."""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    # Source checkout: lib/app/srd_content.py -> repo root is two levels up
    roots.append(Path(__file__).resolve().parent.parent.parent)
    roots.append(Path(os.getcwd()))

    for root in roots:
        candidate = root / _DIR_NAME
        if (candidate / "MANIFEST.json").is_file():
            return candidate
    return None


def is_available() -> bool:
    return content_dir() is not None


def manifest() -> dict:
    """The payload's manifest, or an empty dict when there is no payload."""
    directory = content_dir()
    if directory is None:
        return {}
    try:
        with open(directory / "MANIFEST.json", "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def counts() -> dict:
    """Entry count per category, e.g. {"statblocks": 333, "spells": 338}."""
    declared = manifest().get("counts") or {}
    return {c: int(declared.get(c, 0)) for c in CATEGORIES}


def attribution() -> str:
    """The CC-BY-4.0 notice that must accompany this material."""
    return manifest().get("attribution", "")


def version() -> str:
    return str(manifest().get("source", "")) or "SRD"


def iter_entries(category: str) -> Iterator[tuple[str, dict]]:
    """Yield (key, data) for one category, in manifest order.

    Files are read one at a time rather than loaded up front -- the payload is
    ~670 files and the caller is usually feeding them to a progress bar.
    """
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    directory = content_dir()
    if directory is None:
        return

    listed = manifest().get(category)
    folder = directory / category
    keys = listed if listed else sorted(p.name for p in folder.glob("*.json"))

    for key in keys:
        path = folder / key
        try:
            with open(path, "r", encoding="utf-8") as fh:
                yield key, json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue  # a damaged file shouldn't abort the whole install
