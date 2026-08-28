# lib/ui/colors.py — palette for the D&D Combat Tracker
"""
Every colour in the app, with user overrides.

The names below stay module-level globals so existing call sites keep working,
but they are *rebound* by `apply()` when the user saves a custom palette.
That means consumers must read them as attributes (``colors.HP_LOW_ACTIVE``)
rather than importing the names directly (``from ui.colors import ...``) — a
direct import binds the value once at import time and would never see a change.
"""
from __future__ import annotations

from typing import Any

import app.settings as app_settings

_SETTING_KEY = "palette"
_TINT_SETTING_KEY = "tint_action_cells"

# ── Schema ───────────────────────────────────────────────────────────
# (key, label, default, tooltip) grouped under a heading. The dialog is
# generated from this, so adding a colour here is all that's needed.
PALETTE_SCHEMA: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    ("Turn and Health", [
        ("HP_HEALTHY_ACTIVE", "Active turn", "#2d6a4f",
         "The creature whose turn it is, at healthy HP"),
        ("HP_LOW_ACTIVE", "Bloodied — active", "#b5651d",
         "At or below half HP, and it's their turn"),
        ("HP_LOW_INACTIVE", "Bloodied", "#5e4e2a",
         "At or below half HP"),
        ("HP_ZERO_ACTIVE", "Down — active", "#c0392b",
         "At 0 HP, and it's their turn"),
        ("HP_ZERO_INACTIVE", "Down", "#7b241c",
         "At 0 HP"),
    ]),
    ("Death and Stabilisation", [
        ("DEAD_BG_ACTIVE", "Dead — active", "#808080",
         "Three failed death saves, and it's their turn"),
        ("DEAD_BG_INACTIVE", "Dead", "#555555",
         "Three failed death saves"),
        ("DEAD_TEXT", "Dead text", "#e6e6e6",
         "Text colour on a dead creature's row"),
        ("STABLE_BG_ACTIVE", "Stable — active", "#4a90d9",
         "Stabilised at 0 HP, and it's their turn"),
        ("STABLE_BG_INACTIVE", "Stable", "#2b5aa6",
         "Stabilised at 0 HP"),
    ]),
    ("Special Rows", [
        ("LAIR_ACTION_BG", "Lair action", "#4a2060",
         "Rows that represent a lair action rather than a creature"),
    ]),
    ("Action Tracker", [
        ("BOOL_TRUE_FG", "Available mark", "#4ade80",
         "The ✔ shown when an action is still available"),
        ("BOOL_FALSE_FG", "Used mark", "#f87171",
         "The ✘ shown when an action has been used"),
        ("BOOL_TRUE_BG", "Available tint", "#1a3d2e",
         "Cell tint behind an available action (only when tinting is on)"),
        ("BOOL_FALSE_BG", "Used tint", "#3d1a1a",
         "Cell tint behind a used action (only when tinting is on)"),
    ]),
    ("Interface", [
        ("BG_DARK", "Window background", "#1e1e2e", "Main window and table background"),
        ("BG_PANEL", "Panel background", "#2a2a3c", "Group boxes, menus, toolbar, status bar"),
        ("TEXT_PRIMARY", "Primary text", "#e0dcc8", "Main text colour"),
        ("TEXT_SECONDARY", "Secondary text", "#a09c8c", "Muted labels and hints"),
        ("ACCENT_GOLD", "Accent", "#c8a96e", "Headers, panel titles, primary button"),
        ("ACCENT_GOLD_DIM", "Accent (dim)", "#8a7548", "Selections and subdued accents"),
        ("BORDER", "Borders", "#3a3a4e", "Widget and grid outlines"),
        ("HOVER_HIGHLIGHT", "Hover highlight", "#35354a", "Row and item hover"),
    ]),
    ("Buttons", [
        ("BTN_DAMAGE_BG", "Damage button", "#5c2020", ""),
        ("BTN_DAMAGE_HOVER", "Damage button (hover)", "#7a2a2a", ""),
        ("BTN_HEAL_BG", "Heal button", "#1a4a2e", ""),
        ("BTN_HEAL_HOVER", "Heal button (hover)", "#246b3f", ""),
    ]),
]

DEFAULTS: dict[str, str] = {
    key: default
    for _group, entries in PALETTE_SCHEMA
    for key, _label, default, _tip in entries
}

# Whether action/bonus-action/reaction cells get a tinted background. The ✔/✘
# glyph already carries the information, so the tint is optional.
TINT_ACTION_CELLS_DEFAULT = False


def _is_hex(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return (
        text.startswith("#")
        and len(text) in (4, 7, 9)
        and all(c in "0123456789abcdefABCDEF" for c in text[1:])
    )


def load() -> dict[str, str]:
    """Saved overrides merged over the defaults, ignoring anything malformed."""
    palette = dict(DEFAULTS)
    saved = app_settings.get(_SETTING_KEY) or {}
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key in DEFAULTS and _is_hex(value):
                palette[key] = value.strip()
    return palette


def save(palette: dict[str, str]) -> None:
    """Persist only the entries that actually differ from the defaults."""
    overrides = {
        key: value
        for key, value in palette.items()
        if key in DEFAULTS and _is_hex(value) and value.strip() != DEFAULTS[key]
    }
    app_settings.set(_SETTING_KEY, overrides)


def tint_action_cells() -> bool:
    value = app_settings.get(_TINT_SETTING_KEY)
    if value is None:
        return TINT_ACTION_CELLS_DEFAULT
    return bool(value)


def set_tint_action_cells(enabled: bool) -> None:
    app_settings.set(_TINT_SETTING_KEY, bool(enabled))


def apply(palette: dict[str, str] | None = None) -> dict[str, str]:
    """Rebind the module-level names so every consumer picks the palette up."""
    if palette is None:
        palette = load()
    globals().update(palette)
    # Derived values must be recomputed whenever the source changes.
    globals()["ACTIVE_BAR_COLOR"] = palette["ACCENT_GOLD"]
    return palette


# Bind the names at import so `colors.BG_DARK` etc. always exist.
apply()
