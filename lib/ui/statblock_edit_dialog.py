# ui/statblock_edit_dialog.py
"""
StatblockEditDialog — JSON editor with live StatblockWidget preview.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget

from app.statblock_parser import statblock_key
from ui.json_edit_dialog import JsonEditDialog
from ui.statblock_widget import StatblockWidget


class StatblockEditDialog(JsonEditDialog):
    noun = "Statblock"
    minimum_size = (900, 600)
    initial_size = (1100, 680)
    splitter_sizes = (380, 570)
    editor_minimum_width = 300

    def _make_preview(self) -> QWidget:
        preview = StatblockWidget()
        preview.set_storage(self._api)
        return preview

    def _render_preview(self, data: dict) -> None:
        self._preview.load_statblock(data)

    def _key_for(self, name: str) -> str:
        return statblock_key(name)

    def _save_entry(self, key: str, data: dict) -> None:
        self._api.save_statblock(key, data)

    def _delete_entry(self, key: str) -> None:
        self._api.delete_statblock(key)
