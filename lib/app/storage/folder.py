"""
A folder of JSON files.

This is the backend for "This computer" and, just as importantly, for Dropbox,
Google Drive, OneDrive and iCloud: those services all present themselves to the
operating system as an ordinary directory that a background process keeps in
sync, so pointing this at `~/Dropbox/DnD Tracker` *is* Dropbox support. It
needs no OAuth app, no access token, no refresh path, and it keeps working with
the network off -- the sync client catches up later. See `cloud_folders.py`
for how those directories are found.

    data_dir/
        goblin_caves.json        encounters, flat (backward-compatible)
        players.json
        last_state.json
        statblocks/goblin.json
        spells/fireball.json
        items/bag_of_holding.json

Encounters sit at the root rather than in an `encounters/` subdirectory because
that is where they have always been; moving them would strand every existing
library.
"""
from __future__ import annotations

import json
import os
from typing import Any, List, Optional

from app.storage.base import ENCOUNTERS, StorageBackend

# Everything except encounters lives one level down, in a directory named for
# the collection.
_SUBDIRS = {ENCOUNTERS: ""}


class FolderStorage(StorageBackend):
    """JSON files in a directory tree."""

    provider_id = "local"

    def __init__(self, data_dir: str, provider_id: str = "local") -> None:
        if not data_dir:
            raise ValueError("a data directory is required")
        self.data_dir = os.path.abspath(os.path.expanduser(data_dir))
        self.provider_id = provider_id
        self.location = self.data_dir
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for collection in ("statblocks", "spells", "items"):
            os.makedirs(self._dir(collection), exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    def _dir(self, collection: str) -> str:
        return os.path.join(self.data_dir, _SUBDIRS.get(collection, collection))

    def _path(self, collection: str, key: str) -> str:
        return os.path.join(self._dir(collection), key)

    # ---- contract ----

    def _list(self, collection: str) -> List[str]:
        try:
            return sorted(
                f for f in os.listdir(self._dir(collection))
                if f.endswith(".json") and not f.startswith(".")
            )
        except FileNotFoundError:
            return []

    def _read(self, collection: str, key: str) -> Optional[dict]:
        try:
            with open(self._path(collection, key), "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # A truncated file reads as absent rather than fatal: a cloud sync
            # client that is mid-download should not take the app down.
            return None

    def _write(self, collection: str, key: str, data: Any) -> None:
        path = self._path(collection, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write-then-rename, because these directories are watched by sync
        # clients. A plain truncating write hands Dropbox a half-empty file to
        # upload, and a crash mid-write leaves the only copy corrupt.
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _delete(self, collection: str, key: str) -> None:
        try:
            os.remove(self._path(collection, key))
        except FileNotFoundError:
            pass

    # ---- overrides ----

    def describe(self) -> str:
        return self.data_dir

    def check(self) -> str:
        if not os.path.isdir(self.data_dir):
            raise IOError(f"The folder does not exist: {self.data_dir}")
        if not os.access(self.data_dir, os.R_OK | os.W_OK):
            raise IOError(f"The folder is not readable and writable: {self.data_dir}")
        return super().check()
