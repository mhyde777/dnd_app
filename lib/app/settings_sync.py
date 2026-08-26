# lib/app/settings_sync.py
"""
Carry the *preferences* half of settings.json between machines.

The transport is the storage backend already configured -- the remote API for
anyone using one, or the local data directory, which covers a data dir that
lives in Dropbox or on a NAS. Nothing new to host.

SYNCABLE_KEYS is an allowlist, deliberately. settings.json also holds the
storage API key and the Foundry bridge secret, and a denylist would leak a
future secret the day someone adds one and forgets this file. Anything not
named here stays on the machine it was set on.

Push and pull are explicit. Silent bidirectional sync would need real conflict
resolution, and the failure mode -- a machine quietly overwriting the layout
you just spent an evening arranging -- is worse than pressing a button.
"""
from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any, Optional

from app import settings

# The key the payload lives under in the storage backend. Leading underscore so
# it sorts away from encounters, and both backends filter it out of list().
REMOTE_KEY = "_app_settings.json"

FORMAT_VERSION = 1

# Preferences that mean the same thing on any machine.
SYNCABLE_KEYS: tuple[str, ...] = (
    "panel_layout",         # dock placement, widths, toolbar visibility
    "control_sections",     # Combat Controls sections and their order
    "toolbar_items",        # toolbar contents and order
    "shortcuts",            # rebound keys
    "palette",              # colour overrides
    "tint_action_cells",
    "table_column_widths",
    "statblock_zoom",
    "status_messages_enabled",
    "update_check_enabled",
    "foundry_ignore",       # tokens to keep out of initiative
)

# PC group rosters are deliberately absent: they are pcgroup_*.json files in
# the storage backend, not settings, so they already travel with a shared API
# or a shared data folder. Only *which* group is active is per-machine.

# Named only so the UI can explain the omissions; the allowlist above is what
# actually decides. Keep the reasons accurate if this list grows.
NOT_SYNCED: tuple[tuple[str, str], ...] = (
    ("storage_api_base / storage_api_key", "credentials, and how you reach the sync itself"),
    ("bridge_url / bridge_secret",         "a secret, and the address differs per machine"),
    ("storage_mode / local_data_dir",      "where this machine keeps its files"),
    ("window_geometry / window_state",     "sized for this machine's monitor"),
    ("srd_installed",                      "state of this installation"),
    ("active_pc_group",                    "which roster this machine is running right now"),
)


class _Missing:
    """Sentinel: absent is different from present-and-None."""

    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def machine_name() -> str:
    try:
        return socket.gethostname() or "unknown"
    except Exception:
        return "unknown"


def local_payload() -> dict:
    """The syncable slice of this machine's settings, ready to store."""
    current = settings.load()
    return {
        "format": FORMAT_VERSION,
        "updated_at": _now(),
        "machine": machine_name(),
        "settings": {
            key: current[key] for key in SYNCABLE_KEYS if key in current
        },
    }


def push(storage) -> dict:
    """Write this machine's preferences to the backend. Returns the payload."""
    payload = local_payload()
    storage.put_json(REMOTE_KEY, payload)
    return payload


def fetch(storage) -> Optional[dict]:
    """The stored payload, or None if there isn't one (or it's unreadable)."""
    try:
        payload = storage.get_json(REMOTE_KEY)
    except Exception:
        return None
    if not isinstance(payload, dict) or "settings" not in payload:
        return None
    if not isinstance(payload.get("settings"), dict):
        return None
    return payload


def pull(storage) -> Optional[dict]:
    """Merge stored preferences into this machine's settings.

    Merge, not replace: keys outside the allowlist are left exactly as they
    are, so pulling can never cost you your API key or your data directory.
    Returns the payload that was applied, or None if there was nothing to pull.
    """
    payload = fetch(storage)
    if payload is None:
        return None

    incoming = payload["settings"]
    merged = dict(settings.load())
    for key in SYNCABLE_KEYS:
        if key in incoming:
            merged[key] = incoming[key]
    settings.save(merged)
    return payload


def describe(payload: Optional[dict]) -> str:
    """One line about what is on the server, for the settings dialog."""
    if payload is None:
        return "No settings have been pushed yet."
    when = payload.get("updated_at") or "an unknown time"
    who = payload.get("machine") or "an unknown machine"
    count = len(payload.get("settings") or {})
    return f"Last pushed {when} from {who} ({count} preferences)."


def differences(payload: Optional[dict]) -> list[str]:
    """Syncable keys whose stored value differs from this machine's."""
    if payload is None:
        return []
    incoming = payload.get("settings") or {}
    current = settings.load()
    return [
        key
        for key in SYNCABLE_KEYS
        if incoming.get(key, _MISSING) != current.get(key, _MISSING)
    ]
