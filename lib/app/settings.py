# lib/app/settings.py
"""
Persistent app settings stored in ~/.dnd_tracker_config/settings.json.

Functions here are thin helpers so other modules don't need to import json/os.
"""
from __future__ import annotations

import json
import os
from typing import Any

_CONFIG_DIR = os.path.expanduser("~/.dnd_tracker_config")
_SETTINGS_PATH = os.path.join(_CONFIG_DIR, "settings.json")

_cache: dict | None = None


def settings_exist() -> bool:
    return os.path.exists(_SETTINGS_PATH)


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f) or {}
        except Exception:
            _cache = {}
    else:
        _cache = {}
    return _cache


def save(data: dict) -> None:
    global _cache
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _cache = dict(data)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)
