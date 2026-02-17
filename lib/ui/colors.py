# lib/ui/colors.py — Centralized color palette for the D&D Combat Tracker

# ── Base theme ──────────────────────────────────────────────
BG_DARK = "#1e1e2e"
BG_PANEL = "#2a2a3c"          # slightly lifted for cards / groupboxes
TEXT_PRIMARY = "#e0dcc8"       # warm off-white
TEXT_SECONDARY = "#a09c8c"     # muted for less-important labels
ACCENT_GOLD = "#c8a96e"        # primary accent
ACCENT_GOLD_DIM = "#8a7548"    # subdued gold (borders, inactive)
BORDER = "#3a3a4e"             # subtle borders
HOVER_HIGHLIGHT = "#35354a"    # row / item hover

# ── HP state colors (active / inactive variants) ───────────
HP_HEALTHY_ACTIVE = "#2d6a4f"
HP_HEALTHY_INACTIVE = "#1b3d2e"   # default (no explicit bg needed — only active gets green)

HP_LOW_ACTIVE = "#b5651d"
HP_LOW_INACTIVE = "#5e4e2a"

HP_ZERO_ACTIVE = "#c0392b"
HP_ZERO_INACTIVE = "#7b241c"

DEAD_BG_ACTIVE = "#808080"
DEAD_BG_INACTIVE = "#555555"
DEAD_TEXT = "#e6e6e6"

STABLE_BG_ACTIVE = "#4a90d9"
STABLE_BG_INACTIVE = "#2b5aa6"

# ── Boolean cell tints ──────────────────────────────────────
BOOL_TRUE_BG = "#1a3d2e"      # muted green tint
BOOL_FALSE_BG = "#3d1a1a"     # muted red tint
BOOL_TRUE_FG = "#4ade80"      # bright green checkmark
BOOL_FALSE_FG = "#f87171"     # bright red cross

# ── Button tints ────────────────────────────────────────────
BTN_DAMAGE_BG = "#5c2020"
BTN_DAMAGE_HOVER = "#7a2a2a"
BTN_HEAL_BG = "#1a4a2e"
BTN_HEAL_HOVER = "#246b3f"

# ── Active creature indicator ───────────────────────────────
ACTIVE_BAR_COLOR = ACCENT_GOLD
ACTIVE_BAR_WIDTH = 4
