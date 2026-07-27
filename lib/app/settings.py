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


def set(key: str, value: Any) -> None:
    data = dict(load())
    data[key] = value
    save(data)


# ---- Foundry sync ignore list ----
# Combatants matching any of these are dropped from every Foundry snapshot
# before the app sees them: never added to initiative, never synced.
#   patterns          — name globs matched against combatant and actor name.
#                       No wildcard means an exact (case-insensitive) match.
#   actor_ids         — Foundry actor IDs, to ignore one specific token/actor.
#   player_owned_npcs — blanket rule for summons/companions: a Foundry actor of
#                       type "npc" that a player owns. PCs are type "character"
#                       and real monsters aren't player-owned, so this catches
#                       familiars, summons and effect tokens and nothing else.
_IGNORE_KEY = "foundry_ignore"

IGNORE_PLAYER_OWNED_NPCS_DEFAULT = True


def get_foundry_ignore() -> dict:
    raw = get(_IGNORE_KEY, {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    patterns = [str(p) for p in (raw.get("patterns") or []) if str(p).strip()]
    actor_ids = [str(a) for a in (raw.get("actor_ids") or []) if str(a).strip()]
    player_owned = raw.get("player_owned_npcs")
    if player_owned is None:
        player_owned = IGNORE_PLAYER_OWNED_NPCS_DEFAULT
    return {
        "patterns": patterns,
        "actor_ids": actor_ids,
        "player_owned_npcs": bool(player_owned),
    }


def set_foundry_ignore(patterns: list, actor_ids: list, player_owned_npcs: bool = None) -> None:
    if player_owned_npcs is None:
        player_owned_npcs = get_foundry_ignore()["player_owned_npcs"]
    set(_IGNORE_KEY, {
        "patterns": [str(p).strip() for p in patterns if str(p).strip()],
        "actor_ids": [str(a).strip() for a in actor_ids if str(a).strip()],
        "player_owned_npcs": bool(player_owned_npcs),
    })
