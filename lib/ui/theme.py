# lib/ui/theme.py — QSS stylesheet for the D&D Combat Tracker
from ui import colors


def get_stylesheet() -> str:
    # Read through the module, not via `from ... import`: the palette is
    # rebound at runtime when the user saves custom colours.
    BG_DARK = colors.BG_DARK
    BG_PANEL = colors.BG_PANEL
    TEXT_PRIMARY = colors.TEXT_PRIMARY
    TEXT_SECONDARY = colors.TEXT_SECONDARY
    ACCENT_GOLD = colors.ACCENT_GOLD
    ACCENT_GOLD_DIM = colors.ACCENT_GOLD_DIM
    BORDER = colors.BORDER
    HOVER_HIGHLIGHT = colors.HOVER_HIGHLIGHT
    BTN_DAMAGE_BG = colors.BTN_DAMAGE_BG
    BTN_DAMAGE_HOVER = colors.BTN_DAMAGE_HOVER
    BTN_HEAL_BG = colors.BTN_HEAL_BG
    BTN_HEAL_HOVER = colors.BTN_HEAL_HOVER

    return f"""
    /* ── Global ──────────────────────────────────────── */
    QMainWindow, QDialog {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
    }}

    /* ── GroupBox (card-style panels) ────────────────── */
    QGroupBox {{
        background-color: {BG_PANEL};
        border: 1px solid {BORDER};
        border-radius: 6px;
        margin-top: 14px;
        padding: 10px 6px 6px 6px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 2px 8px;
        color: {ACCENT_GOLD};
    }}

    /* ── Table ───────────────────────────────────────── */
    QTableView {{
        gridline-color: {BORDER};
        background-color: {BG_DARK};
        selection-background-color: {HOVER_HIGHLIGHT};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
    }}
    QTableView::item:hover {{
        background-color: {HOVER_HIGHLIGHT};
    }}

    QHeaderView::section {{
        background-color: {BG_PANEL};
        color: {ACCENT_GOLD};
        border: 1px solid {BORDER};
        padding: 4px;
        font-weight: 600;
    }}

    /* ── Buttons ─────────────────────────────────────── */
    QPushButton {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 5px 12px;
    }}
    QPushButton:hover {{
        border-color: {ACCENT_GOLD};
        color: {ACCENT_GOLD};
    }}
    QPushButton:pressed {{
        background-color: {HOVER_HIGHLIGHT};
    }}

    /* Primary action (Next turn) — the most-used control in the window */
    QPushButton#primaryButton {{
        background-color: {ACCENT_GOLD_DIM};
        color: {TEXT_PRIMARY};
        border-color: {ACCENT_GOLD};
        font-weight: 600;
    }}
    QPushButton#primaryButton:hover {{
        background-color: {ACCENT_GOLD};
        color: {BG_DARK};
    }}

    /* Damage button */
    QPushButton#damageButton {{
        background-color: {BTN_DAMAGE_BG};
    }}
    QPushButton#damageButton:hover {{
        background-color: {BTN_DAMAGE_HOVER};
        border-color: #e74c3c;
    }}

    /* Heal button */
    QPushButton#healButton {{
        background-color: {BTN_HEAL_BG};
    }}
    QPushButton#healButton:hover {{
        background-color: {BTN_HEAL_HOVER};
        border-color: #2ecc71;
    }}

    /* ── Inputs ──────────────────────────────────────── */
    QLineEdit, QSpinBox {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 3px;
        padding: 3px 6px;
    }}
    QLineEdit:focus, QSpinBox:focus {{
        border-color: {ACCENT_GOLD};
    }}

    /* ── List widgets ────────────────────────────────── */
    QListWidget {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
    }}
    QListWidget::item:hover {{
        background-color: {HOVER_HIGHLIGHT};
    }}
    QListWidget::item:selected {{
        background-color: {ACCENT_GOLD_DIM};
        color: {TEXT_PRIMARY};
    }}

    /* ── Menu / Toolbar ──────────────────────────────── */
    QMenuBar {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
    }}
    QMenuBar::item:selected {{
        background-color: {ACCENT_GOLD_DIM};
    }}
    QMenu {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
    }}
    QMenu::item:selected {{
        background-color: {ACCENT_GOLD_DIM};
    }}
    QToolBar {{
        background-color: {BG_PANEL};
        border-bottom: 1px solid {BORDER};
        spacing: 4px;
    }}

    QToolBar QToolButton {{
        color: {TEXT_PRIMARY};
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QToolBar QToolButton:hover {{
        border-color: {ACCENT_GOLD};
        color: {ACCENT_GOLD};
        background-color: {HOVER_HIGHLIGHT};
    }}
    QToolBar QToolButton:pressed {{
        background-color: {ACCENT_GOLD_DIM};
    }}
    QToolBar::separator {{
        background-color: {BORDER};
        width: 1px;
        margin: 4px 6px;
    }}

    /* ── Dock panels ─────────────────────────────────── */
    QDockWidget {{
        color: {ACCENT_GOLD};
        font-weight: 600;
    }}
    QDockWidget::title {{
        background-color: {BG_PANEL};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 5px 8px;
        text-align: left;
    }}
    QDockWidget::close-button, QDockWidget::float-button {{
        border: none;
        background: transparent;
        padding: 2px;
    }}
    QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
        background-color: {HOVER_HIGHLIGHT};
        border-radius: 3px;
    }}
    QMainWindow::separator {{
        background-color: {BG_DARK};
        width: 5px;
        height: 5px;
    }}
    QMainWindow::separator:hover {{
        background-color: {ACCENT_GOLD_DIM};
    }}

    /* ── Status bar ──────────────────────────────────── */
    QStatusBar {{
        background-color: {BG_PANEL};
        color: {TEXT_SECONDARY};
        border-top: 1px solid {BORDER};
    }}

    /* ── Combat info labels ──────────────────────────── */
    QLabel#combatInfoLabel {{
        font-size: 18px;
        font-weight: 600;
        color: {ACCENT_GOLD};
    }}

    /* ── Scroll area (conditions dropdown etc) ───────── */
    QScrollArea {{
        border: none;
    }}

    /* ── Checkbox styling ────────────────────────────── */
    QCheckBox {{
        color: {TEXT_PRIMARY};
        spacing: 6px;
    }}

    /* ── Dialog button box ───────────────────────────── */
    QDialogButtonBox > QPushButton {{
        min-width: 70px;
    }}

    /* ── Tooltips (statblock condition/spell hover) ───── */
    QToolTip {{
        background-color: #FEF5E5;
        color: #1a1a1a;
        border: 1px solid #C9801A;
        padding: 4px;
    }}
    """
