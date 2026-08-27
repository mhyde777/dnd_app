# ui/json_edit_dialog.py
"""
JsonEditDialog — the shared "edit stored JSON with a live preview" dialog.

Spells and statblocks are edited the same way: a JSON pane on the left, a
rendered preview on the right, and Save/Delete against the storage backend.
The two used to be separate 158-line files that differed only in the preview
widget and which storage methods they called, so everything except those hooks
lives here.

Subclasses supply the nouns and the four hooks below; nothing else should need
overriding.
"""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QPlainTextEdit, QSplitter,
    QPushButton, QLabel, QMessageBox, QWidget,
)


class JsonEditDialog(QDialog):
    """Edit or delete one stored JSON entry.

    After exec_():
      self.action     — "saved" | "deleted" | None
      self.saved_key  — new key (if action == "saved")
      self.saved_data — new data dict (if action == "saved")
    """

    #: Displayed in the title bar and the delete confirmation ("Spell").
    noun = "Entry"
    #: (minimum, initial) window size, and the splitter's starting pane widths.
    minimum_size = (800, 520)
    initial_size = (1000, 620)
    splitter_sizes = (340, 510)
    editor_minimum_width = 280

    def __init__(self, storage_api, key: str, data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {self.noun}")
        self.setMinimumSize(*self.minimum_size)
        self.resize(*self.initial_size)

        self._api          = storage_api
        self._original_key = key
        self.action        = None
        self.saved_key     = None
        self.saved_data    = None

        self._build_ui(data)
        self._connect_signals()

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _make_preview(self) -> QWidget:
        """Build the (empty) preview widget for the right-hand pane."""
        raise NotImplementedError

    def _render_preview(self, data: dict) -> None:
        """Show `data` in the preview widget."""
        raise NotImplementedError

    def _key_for(self, name: str) -> str:
        """The storage key an entry called `name` should be filed under."""
        raise NotImplementedError

    def _save_entry(self, key: str, data: dict) -> None:
        raise NotImplementedError

    def _delete_entry(self, key: str) -> None:
        raise NotImplementedError

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
        self._editor.setMinimumWidth(self.editor_minimum_width)
        splitter.addWidget(self._editor)

        self._preview = self._make_preview()
        self._render_preview(data)
        splitter.addWidget(self._preview)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes(list(self.splitter_sizes))
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
        try:
            data = json.loads(self._editor.toPlainText())
        except json.JSONDecodeError as exc:
            self._warning.setText(f"Invalid JSON: {exc}")
            self._warning.setVisible(True)
            return
        self._render_preview(data)
        self._warning.setVisible(False)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _save(self):
        try:
            data = json.loads(self._editor.toPlainText())
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "Invalid JSON", str(exc))
            return

        name    = data.get("name", "")
        new_key = self._key_for(name) if name else self._original_key

        try:
            self._save_entry(new_key, data)
            # A rename writes under the new key, so the old one has to go or
            # the entry is left duplicated under both.
            if new_key != self._original_key:
                self._delete_entry(self._original_key)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return

        self.action     = "saved"
        self.saved_key  = new_key
        self.saved_data = data
        self.accept()

    def _delete(self):
        reply = QMessageBox.question(
            self, f"Delete {self.noun}",
            f"Delete '{self._original_key}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self._delete_entry(self._original_key)
        except Exception as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))
            return

        self.action = "deleted"
        self.accept()
