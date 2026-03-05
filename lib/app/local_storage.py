# lib/app/local_storage.py
"""
Local filesystem storage backend.

Implements the same public interface as StorageAPI so the rest of the app
can use either interchangeably.

Directory layout under data_dir:
    data_dir/
        <encounter>.json        ← encounters stored flat (backward-compat)
        players.json            ← player roster
        last_state.json         ← auto-saved combat state
        statblocks/
            <name>.json
        spells/
            <name>.json
"""
from __future__ import annotations

import json
import os
from typing import Any, List, Optional

from app.creature import CustomEncoder


class LocalStorage:
    """Local filesystem backend with the same interface as StorageAPI."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = os.path.expanduser(data_dir)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for sub in ("statblocks", "spells"):
            os.makedirs(os.path.join(self.data_dir, sub), exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    # ---- internal helpers ----

    def _enc_path(self, key: str) -> str:
        return os.path.join(self.data_dir, key)

    def _sb_path(self, key: str) -> str:
        return os.path.join(self.data_dir, "statblocks", key)

    def _spell_path(self, key: str) -> str:
        return os.path.join(self.data_dir, "spells", key)

    @staticmethod
    def _read_json(path: str) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_json(path: str, data: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _list_json(dirpath: str) -> List[str]:
        try:
            return sorted(
                f for f in os.listdir(dirpath)
                if f.endswith(".json") and not f.startswith(".")
            )
        except FileNotFoundError:
            return []

    # ---- Encounters (flat in data_dir) ----

    def list(self) -> List[str]:
        return self._list_json(self.data_dir)

    def get(self, key: str) -> Optional[dict]:
        return self._read_json(self._enc_path(key))

    def put(self, key: str, data: Any) -> None:
        self._write_json(self._enc_path(key), data)

    def delete(self, key: str) -> None:
        path = self._enc_path(key)
        if os.path.exists(path):
            os.remove(path)

    def put_json(self, key: str, obj: dict) -> None:
        text = json.dumps(obj, cls=CustomEncoder, ensure_ascii=False)
        self._write_json(self._enc_path(key), json.loads(text))

    def get_json(self, key: str) -> Optional[dict]:
        return self.get(key)

    # ---- Statblocks ----

    def list_statblock_keys(self) -> List[str]:
        return self._list_json(os.path.join(self.data_dir, "statblocks"))

    def get_statblock(self, key: str) -> Optional[dict]:
        return self._read_json(self._sb_path(key))

    def save_statblock(self, key: str, data: dict) -> bool:
        self._write_json(self._sb_path(key), data)
        return True

    def delete_statblock(self, key: str) -> bool:
        path = self._sb_path(key)
        if os.path.exists(path):
            os.remove(path)
        return True

    # ---- Spells ----

    def list_spell_keys(self) -> List[str]:
        return self._list_json(os.path.join(self.data_dir, "spells"))

    def get_spell(self, key: str) -> Optional[dict]:
        return self._read_json(self._spell_path(key))

    def save_spell(self, key: str, data: dict) -> bool:
        self._write_json(self._spell_path(key), data)
        return True

    def delete_spell(self, key: str) -> bool:
        path = self._spell_path(key)
        if os.path.exists(path):
            os.remove(path)
        return True

