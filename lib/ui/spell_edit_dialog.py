# ui/spell_edit_dialog.py
"""
SpellEditDialog — JSON editor with live HTML spell-card preview.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QTextBrowser, QWidget

from app.spell_parser import spell_key
from ui.json_edit_dialog import JsonEditDialog
from ui.lookup_dialog import _build_spell_html


class SpellEditDialog(JsonEditDialog):
    noun = "Spell"

    def _make_preview(self) -> QWidget:
        preview = QTextBrowser()
        preview.setOpenLinks(False)
        return preview

    def _render_preview(self, data: dict) -> None:
        self._preview.setHtml(_build_spell_html(data))

    def _key_for(self, name: str) -> str:
        return spell_key(name)

    def _save_entry(self, key: str, data: dict) -> None:
        self._api.save_spell(key, data)

    def _delete_entry(self, key: str) -> None:
        self._api.delete_spell(key)
