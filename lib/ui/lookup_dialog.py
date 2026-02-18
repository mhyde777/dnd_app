# ui/lookup_dialog.py
"""
LookupDialog — non-modal reference panel for spells, monsters, and conditions.

Tabs:
  Spells    — fetched from Storage API; renders full spell card
  Monsters  — fetched from Storage API; reuses StatblockWidget
  Conditions — local data from app.conditions; instant display
"""
from __future__ import annotations

import threading
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QTabWidget, QWidget, QTextBrowser, QSplitter, QLabel,
)

from app.conditions import CONDITIONS
from ui.statblock_widget import StatblockWidget

# ── Colour palette (matches statblock_widget.py) ────────────────────────────
_BG     = "#FEF5E5"
_MAROON = "#58180D"
_RED    = "#7A1F1F"
_ORANGE = "#C9801A"
_TEXT   = "#1a1a1a"

_SPELL_ORDINALS = {
    0: "Cantrip", 1: "1st", 2: "2nd", 3: "3rd",
    4: "4th", 5: "5th", 6: "6th", 7: "7th", 8: "8th", 9: "9th",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _key_to_display(key: str) -> str:
    """Convert a storage key to a human-readable name.

    'mind_flayer.json' → 'Mind Flayer'
    """
    return key.replace(".json", "").replace("_", " ").title()


def _placeholder_html(text: str) -> str:
    return (
        f'<body style="background-color:{_BG}; color:#999; '
        f'font-family:&quot;Palatino Linotype&quot;,Palatino,serif;">'
        f'<p style="margin:20px; text-align:center; font-style:italic;">'
        f'{text}</p></body>'
    )


def _build_spell_html(data: dict) -> str:
    """Render a spell dict as styled HTML."""
    name   = data.get("name", "Unknown")
    level  = data.get("level", 0)
    school = data.get("school", "")
    conc   = data.get("concentration", False)

    ord_str  = _SPELL_ORDINALS.get(level, f"{level}th")
    em_dash  = "\u2014"
    if level == 0:
        subtitle = f"Cantrip{(' ' + em_dash + ' ' + school) if school else ''}"
    else:
        subtitle = f"{ord_str}-level {school}".strip()

    p = [
        f'<html><body style="background-color:{_BG}; '
        f'font-family:&quot;Palatino Linotype&quot;,Palatino,serif; '
        f'font-size:13px; color:{_TEXT}; margin:8px;">',

        f'<table width="100%" style="border-collapse:collapse; margin-bottom:2px;">'
        f'<tr><td style="font-size:22px; font-weight:bold; color:{_MAROON}; '
        f'border-bottom:3px solid {_ORANGE}; padding:0 0 2px 0;">'
        f'{name}</td></tr></table>',
    ]

    if subtitle:
        p.append(
            f'<p style="font-style:italic; font-size:11px; color:#444; margin:0 0 6px 0;">'
            f'{subtitle}</p>'
        )

    for label, field in [
        ("Casting Time", "casting_time"),
        ("Range",        "range"),
        ("Components",   "components"),
        ("Duration",     "duration"),
    ]:
        val = data.get(field, "")
        if val:
            if field == "duration" and conc:
                val = "\u25C6 " + val
            p.append(
                f'<p style="margin:2px 0;">'
                f'<b style="color:{_RED};">{label}:</b> {val}</p>'
            )

    atksave = data.get("attack_save", "")
    dmgeff  = data.get("damage_effect", "")
    if atksave or dmgeff:
        parts = []
        if atksave:
            parts.append(f"<b style='color:{_RED};'>Attack/Save:</b> {atksave}")
        if dmgeff:
            parts.append(f"<b style='color:{_RED};'>Effect:</b> {dmgeff}")
        p.append(f'<p style="margin:2px 0;">{" &nbsp;&nbsp; ".join(parts)}</p>')

    desc = data.get("description", "")
    if desc:
        p.append(f'<hr style="border:1px solid {_ORANGE}; margin:6px 0;">')
        p.append(
            f'<p style="margin:4px 0; line-height:1.5;">'
            f'{desc.replace(chr(10), "<br>")}</p>'
        )

    for fn in data.get("footnotes", []):
        p.append(
            f'<p style="margin:6px 0 0 0; font-style:italic; color:#555; font-size:11px;">'
            f'{fn}</p>'
        )

    p.append('</body></html>')
    return "".join(p)


def _build_condition_html(name: str, description: str) -> str:
    """Render a condition as styled HTML."""
    lines    = description.split("\n")
    preamble = lines[0] if lines else ""
    bullets  = lines[1:] if len(lines) > 1 else []

    p = [
        f'<html><body style="background-color:{_BG}; '
        f'font-family:&quot;Palatino Linotype&quot;,Palatino,serif; '
        f'font-size:13px; color:{_TEXT}; margin:8px;">',

        f'<table width="100%" style="border-collapse:collapse; margin-bottom:2px;">'
        f'<tr><td style="font-size:22px; font-weight:bold; color:{_MAROON}; '
        f'border-bottom:3px solid {_ORANGE}; padding:0 0 2px 0;">'
        f'{name.title()}</td></tr></table>',
    ]

    if preamble:
        p.append(
            f'<p style="font-style:italic; color:#444; margin:6px 0;">'
            f'{preamble}</p>'
        )

    if bullets:
        p.append('<ul style="margin:4px 0; padding-left:20px; line-height:1.6;">')
        for bullet in bullets:
            if ". " in bullet:
                title, rest = bullet.split(". ", 1)
                p.append(f'<li><b style="color:{_RED};">{title}.</b> {rest}</li>')
            else:
                p.append(f'<li>{bullet}</li>')
        p.append('</ul>')

    p.append('</body></html>')
    return "".join(p)


# ── Reusable tab layout ───────────────────────────────────────────────────────

class _SearchListPanel(QWidget):
    """Left panel: search box + list widget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search\u2026")
        self.search.setClearButtonEnabled(True)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)

        layout.addWidget(self.search)
        layout.addWidget(self.list)
        self.setMinimumWidth(160)


class _LookupTab(QWidget):
    """Horizontal splitter: search/list on the left, detail widget on the right."""
    def __init__(self, detail_widget: QWidget, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._splitter = QSplitter(Qt.Horizontal, self)

        self.panel = _SearchListPanel()
        self._splitter.addWidget(self.panel)
        self._splitter.addWidget(detail_widget)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([200, 480])

        layout.addWidget(self._splitter)

    # Convenience passthrough
    @property
    def search(self) -> QLineEdit:
        return self.panel.search

    @property
    def list(self) -> QListWidget:
        return self.panel.list


# ── Main dialog ───────────────────────────────────────────────────────────────

class LookupDialog(QDialog):
    """Non-modal reference lookup — Spells | Monsters | Conditions.

    Pass ``storage_api`` (a StorageAPI instance or None). When None the spell
    and monster tabs display a configuration notice.
    """

    _spell_keys_ready   = pyqtSignal(list)
    _monster_keys_ready = pyqtSignal(list)
    _spell_loaded       = pyqtSignal(object)    # dict | None
    _monster_loaded     = pyqtSignal(object)    # dict | None

    def __init__(self, storage_api, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reference Lookup")
        self.setMinimumSize(720, 520)
        self.resize(860, 600)
        # Don't destroy on close — caller reuses the same instance
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._api = storage_api
        self._all_spell_keys:   list[str] = []
        self._all_monster_keys: list[str] = []

        self._build_ui()
        self._connect_signals()
        self._start_background_loads()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self._tabs = QTabWidget(self)

        # ── Spells tab
        self._spell_browser = QTextBrowser()
        self._spell_browser.setOpenLinks(False)
        self._spell_browser.setHtml(_placeholder_html("No spell selected."))
        self._spell_tab = _LookupTab(self._spell_browser)
        self._tabs.addTab(self._spell_tab, "Spells")

        # ── Monsters tab
        self._monster_widget = StatblockWidget()
        self._monster_widget.set_storage_api(self._api)
        self._monster_tab = _LookupTab(self._monster_widget)
        self._tabs.addTab(self._monster_tab, "Monsters")

        # ── Conditions tab (local — always available)
        self._condition_browser = QTextBrowser()
        self._condition_browser.setOpenLinks(False)
        self._condition_browser.setHtml(_placeholder_html("No condition selected."))
        self._condition_tab = _LookupTab(self._condition_browser)
        self._tabs.addTab(self._condition_tab, "Conditions")

        root.addWidget(self._tabs)

        # Populate conditions immediately (no API needed)
        self._all_condition_keys = sorted(CONDITIONS.keys())
        for key in self._all_condition_keys:
            item = QListWidgetItem(key.title())
            item.setData(Qt.UserRole, key)
            self._condition_tab.list.addItem(item)

        # If no storage API, leave a note in the remote tabs
        if self._api is None:
            msg = "Storage API not configured — spell and monster data unavailable."
            self._spell_browser.setHtml(_placeholder_html(msg))
            self._monster_widget.clear_statblock()

    # ── Signal wiring ────────────────────────────────────────────────────────

    def _connect_signals(self):
        self._spell_keys_ready.connect(self._on_spell_keys_loaded)
        self._monster_keys_ready.connect(self._on_monster_keys_loaded)
        self._spell_loaded.connect(self._on_spell_loaded)
        self._monster_loaded.connect(self._on_monster_loaded)

        self._spell_tab.search.textChanged.connect(self._filter_spells)
        self._monster_tab.search.textChanged.connect(self._filter_monsters)
        self._condition_tab.search.textChanged.connect(self._filter_conditions)

        self._spell_tab.list.currentItemChanged.connect(self._select_spell)
        self._monster_tab.list.currentItemChanged.connect(self._select_monster)
        self._condition_tab.list.currentItemChanged.connect(self._select_condition)

    # ── Background key loading ────────────────────────────────────────────────

    def _start_background_loads(self):
        if self._api is None:
            return

        def _load_spells():
            try:
                keys = self._api.list_spell_keys()
                self._spell_keys_ready.emit(sorted(keys))
            except Exception:
                self._spell_keys_ready.emit([])

        def _load_monsters():
            try:
                keys = self._api.list_statblock_keys()
                self._monster_keys_ready.emit(sorted(keys))
            except Exception:
                self._monster_keys_ready.emit([])

        threading.Thread(target=_load_spells,   daemon=True).start()
        threading.Thread(target=_load_monsters, daemon=True).start()

    def _on_spell_keys_loaded(self, keys: list):
        self._all_spell_keys = keys
        self._populate_list(self._spell_tab.list, keys)

    def _on_monster_keys_loaded(self, keys: list):
        self._all_monster_keys = keys
        self._populate_list(self._monster_tab.list, keys)

    @staticmethod
    def _populate_list(widget: QListWidget, keys: list):
        widget.clear()
        for key in keys:
            item = QListWidgetItem(_key_to_display(key))
            item.setData(Qt.UserRole, key)
            widget.addItem(item)

    # ── Filtering ────────────────────────────────────────────────────────────

    def _filter_spells(self, text: str):
        self._apply_filter(self._spell_tab.list, self._all_spell_keys, text)

    def _filter_monsters(self, text: str):
        self._apply_filter(self._monster_tab.list, self._all_monster_keys, text)

    @staticmethod
    def _apply_filter(widget: QListWidget, all_keys: list, text: str):
        text = text.lower().strip()
        widget.clear()
        for key in all_keys:
            display = _key_to_display(key)
            if text in display.lower():
                item = QListWidgetItem(display)
                item.setData(Qt.UserRole, key)
                widget.addItem(item)

    def _filter_conditions(self, text: str):
        text = text.lower().strip()
        self._condition_tab.list.clear()
        for key in self._all_condition_keys:
            if text in key:
                item = QListWidgetItem(key.title())
                item.setData(Qt.UserRole, key)
                self._condition_tab.list.addItem(item)

    # ── Item selection ────────────────────────────────────────────────────────

    def _select_spell(self, current: Optional[QListWidgetItem], _prev):
        if current is None or self._api is None:
            return
        key = current.data(Qt.UserRole)
        self._spell_browser.setHtml(_placeholder_html("Loading\u2026"))

        def _load():
            try:
                data = self._api.get_spell(key)
                self._spell_loaded.emit(data)
            except Exception:
                self._spell_loaded.emit(None)

        threading.Thread(target=_load, daemon=True).start()

    def _select_monster(self, current: Optional[QListWidgetItem], _prev):
        if current is None or self._api is None:
            return
        key = current.data(Qt.UserRole)
        self._monster_widget.clear_statblock()

        def _load():
            try:
                data = self._api.get_statblock(key)
                self._monster_loaded.emit(data)
            except Exception:
                self._monster_loaded.emit(None)

        threading.Thread(target=_load, daemon=True).start()

    def _select_condition(self, current: Optional[QListWidgetItem], _prev):
        if current is None:
            return
        key = current.data(Qt.UserRole)
        desc = CONDITIONS.get(key)
        if desc:
            self._condition_browser.setHtml(_build_condition_html(key, desc))
        else:
            self._condition_browser.setHtml(_placeholder_html("Condition not found."))

    # ── Data ready ────────────────────────────────────────────────────────────

    def _on_spell_loaded(self, data):
        if data:
            self._spell_browser.setHtml(_build_spell_html(data))
        else:
            self._spell_browser.setHtml(_placeholder_html("Spell not found in library."))

    def _on_monster_loaded(self, data):
        if data:
            self._monster_widget.load_statblock(data)
        else:
            self._monster_widget.clear_statblock()

    # ── Focus helper (called by opener) ──────────────────────────────────────

    def focus_search(self):
        """Activate the search box of the currently-visible tab."""
        idx = self._tabs.currentIndex()
        tabs = [self._spell_tab, self._monster_tab, self._condition_tab]
        if 0 <= idx < len(tabs):
            tabs[idx].search.setFocus()
            tabs[idx].search.selectAll()
