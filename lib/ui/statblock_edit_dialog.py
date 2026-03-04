# ui/statblock_edit_dialog.py
"""
StatblockEditDialog — JSON editor with live StatblockWidget preview.
"""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QPlainTextEdit, QSplitter,
    QPushButton, QLabel, QMessageBox,
)

from app.statblock_parser import statblock_key
from ui.statblock_widget import StatblockWidget


class StatblockEditDialog(QDialog):
    """Edit or delete a statblock stored in the Storage API.

    After exec_():
      self.action  — "saved" | "deleted" | None
      self.saved_key  — new key (if action == "saved")
      self.saved_data — new data dict (if action == "saved")
    """

    def __init__(self, storage_api, key: str, data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Statblock")
        self.setMinimumSize(900, 600)
        self.resize(1100, 680)

        self._api          = storage_api
        self._original_key = key
        self.action        = None
        self.saved_key     = None
        self.saved_data    = None

        self._build_ui(data)
        self._connect_signals()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build_ui(self, data: dict):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Warning banner (hidden by default)
        self._warning = QLabel()
        self._warning.setStyleSheet(
            "background: #fffacd; color: #7a5000; padding: 4px 8px; border-radius: 3px;"
        )
        self._warning.setVisible(False)
        root.addWidget(self._warning)

        # Splitter: JSON editor | preview
        splitter = QSplitter(Qt.Horizontal)

        self._editor = QPlainTextEdit()
        self._editor.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
        self._editor.setMinimumWidth(300)
        splitter.addWidget(self._editor)

        self._preview = StatblockWidget()
        self._preview.set_storage_api(self._api)
        self._preview.load_statblock(data)
        splitter.addWidget(self._preview)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([380, 570])
        root.addWidget(splitter, stretch=1)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)

        self._save_btn   = QPushButton("Save")
        self._delete_btn = QPushButton("Delete")
        self._cancel_btn = QPushButton("Cancel")

        self._save_btn.setDefault(True)
        btn_row.addStretch()
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

        # Debounce timer for live preview
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)

    def _connect_signals(self):
        self._editor.textChanged.connect(self._debounce.start)
        self._debounce.timeout.connect(self._update_preview)
        self._save_btn.clicked.connect(self._save)
        self._delete_btn.clicked.connect(self._delete)
        self._cancel_btn.clicked.connect(self.reject)

    # ── Live preview ─────────────────────────────────────────────────────────

    def _update_preview(self):
        text = self._editor.toPlainText()
        try:
            data = json.loads(text)
            self._preview.load_statblock(data)
            self._warning.setVisible(False)
        except json.JSONDecodeError as exc:
            self._warning.setText(f"Invalid JSON: {exc}")
            self._warning.setVisible(True)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _save(self):
        text = self._editor.toPlainText()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "Invalid JSON", str(exc))
            return

        name    = data.get("name", "")
        new_key = statblock_key(name) if name else self._original_key

        try:
            self._api.save_statblock(new_key, data)
            if new_key != self._original_key:
                self._api.delete_statblock(self._original_key)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return

        self.action     = "saved"
        self.saved_key  = new_key
        self.saved_data = data
        self.accept()

    def _delete(self):
        reply = QMessageBox.question(
            self, "Delete Statblock",
            f"Delete '{self._original_key}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self._api.delete_statblock(self._original_key)
        except Exception as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))
            return

        self.action = "deleted"
        self.accept()
