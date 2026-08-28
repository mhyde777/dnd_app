# lib/app/settings.py
"""
Persistent app settings stored as settings.json in the config directory.

The location comes from app.paths, so DND_TRACKER_CONFIG_DIR redirects it.

Functions here are thin helpers so other modules don't need to import json/os.
"""
from __future__ import annotations

import json
import os
from typing import Any

from app.paths import config_dir, config_path

_cache: dict | None = None


def settings_path() -> str:
    return config_path("settings.json")


def settings_exist() -> bool:
    return os.path.exists(settings_path())


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    path = settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _cache = json.load(f) or {}
        except Exception:
            _cache = {}
    else:
        _cache = {}
    return _cache


def save(data: dict) -> None:
    global _cache
    os.makedirs(config_dir(), exist_ok=True)
    path = settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    # This file holds the storage API key and the Foundry secret, so it should
    # not be group- or world-readable. chmod is a no-op on Windows.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    _cache = dict(data)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set(key: str, value: Any) -> None:
    data = dict(load())
    data[key] = value
    save(data)


def update(values: dict) -> None:
    """Merge several keys in one write.

    save() replaces the file wholesale, so writing keys one at a time is both
    several disk writes and a wider window in which a crash leaves half the
    change applied.
    """
    data = dict(load())
    data.update(values)
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
