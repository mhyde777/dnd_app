# ui/statblock_import_dialog.py
"""
StatblockImportDialog — paste D&D Beyond statblock text, preview it live,
then save it to the storage API.

Usage:
    dlg = StatblockImportDialog(storage_api=self.storage_api, parent=self)
    if dlg.exec_() == QDialog.Accepted:
        key, data = dlg.saved_key, dlg.saved_data
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSizePolicy,
)

from app.statblock_parser import parse_statblock, validate_statblock, statblock_key
from ui.statblock_widget import StatblockWidget


class StatblockImportDialog(QDialog):
    """
    Dialog for importing a D&D Beyond statblock via paste-and-parse.

    After a successful save, `saved_key` and `saved_data` hold the stored
    key (e.g. "goblin.json") and the parsed dict respectively.
    """

    def __init__(self, storage_api=None, parent=None):
        super().__init__(parent)
        self.storage_api = storage_api

        self._parsed_data: Optional[dict] = None
        self.saved_key:  Optional[str]  = None
        self.saved_data: Optional[dict] = None

        self.setWindowTitle("Import Statblock")
        self.resize(480, 800)
        self.setMinimumWidth(420)
        self.setMinimumHeight(500)

        self._build_ui()

        # 500 ms debounce timer — starts/restarts on every keystroke
        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(500)
        self._parse_timer.timeout.connect(self._do_parse)

        self.text_edit.textChanged.connect(self._on_text_changed)

    # ── Layout ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)

        # ---- Text input header row ----
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Paste D&D Beyond statblock text:"))
        header_row.addStretch()
        self._toggle_btn = QPushButton("Hide")
        self._toggle_btn.setFixedWidth(54)
        self._toggle_btn.clicked.connect(self._toggle_text_panel)
        header_row.addWidget(self._toggle_btn)
        layout.addLayout(header_row)

        # ---- Text input ----
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Paste your D&D Beyond statblock text here…\n"
            "The preview updates automatically after you stop typing."
        )
        self.text_edit.setFixedHeight(150)
        layout.addWidget(self.text_edit)

        # ---- Warning banner (hidden until needed) ----
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._warning.setStyleSheet(
            "background:#FFF3CD; color:#856404;"
            "border:1px solid #FFEEBA; padding:6px; border-radius:3px;"
        )
        self._warning.hide()
        layout.addWidget(self._warning)

        # ---- Live preview ----
        self.preview = StatblockWidget()
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.preview, stretch=1)

        # ---- Bottom bar ----
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addWidget(QLabel("Creature name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Goblin")
        self.name_edit.setToolTip(
            "Overrides the parsed name. Determines the storage key."
        )
        bottom.addWidget(self.name_edit, stretch=1)

        self._save_btn = QPushButton("Save")
        self._save_btn.setEnabled(False)
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save)
        bottom.addWidget(self._save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        layout.addLayout(bottom)

    # ── Toggle text panel ─────────────────────────────────────────────

    def _toggle_text_panel(self) -> None:
        visible = self.text_edit.isVisible()
        self.text_edit.setVisible(not visible)
        self._toggle_btn.setText("Show" if visible else "Hide")

    # ── Parse pipeline ────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        """Restart the debounce timer on every keystroke."""
        self._parse_timer.start()

    def _do_parse(self) -> None:
        text = self.text_edit.toPlainText().strip()

        if not text:
            self._parsed_data = None
            self.preview.clear_statblock()
            self._warning.hide()
            self._save_btn.setEnabled(False)
            return

        try:
            data = parse_statblock(text)
        except Exception as exc:
            self._show_warning(f"Parse error: {exc}")
            self._parsed_data = None
            self._save_btn.setEnabled(False)
            return

        self._parsed_data = data

        # Warnings from validator
        warnings = validate_statblock(data)
        if warnings:
            self._show_warning("  •  ".join(warnings))
        else:
            self._warning.hide()

        # Update preview
        self.preview.load_statblock(data)

        # Pre-fill name only if the field is still empty
        parsed_name = data.get("name", "")
        if parsed_name and not self.name_edit.text().strip():
            self.name_edit.setText(parsed_name)

        self._save_btn.setEnabled(True)

        # Collapse the text panel after the first successful parse
        if self.text_edit.isVisible():
            self._toggle_text_panel()

    def _show_warning(self, message: str) -> None:
        self._warning.setText(f"\u26a0  {message}")
        self._warning.show()

    # ── Save ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._parsed_data is None:
            return

        name = self.name_edit.text().strip()
        if not name:
            self._show_warning("Enter a creature name before saving.")
            return

        key = statblock_key(name)

        if self.storage_api is None:
            self._show_warning(
                "Storage API is not configured — statblock cannot be saved remotely. "
                "Connect to a storage server in settings."
            )
            return

        try:
            self.storage_api.save_statblock(key, self._parsed_data)
        except Exception as exc:
            self._show_warning(f"Save failed: {exc}")
            return

        self.saved_key  = key
        self.saved_data = self._parsed_data
        self.accept()
