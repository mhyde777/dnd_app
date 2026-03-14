# ui/bulk_item_import_dialog.py
"""
BulkItemImportDialog — paste a D&D Beyond item list, parse it, preview the
results, and save selected items to storage.

Legacy items are included when no non-legacy counterpart exists in the paste.
Items without a "View Details Page" line (unowned sourcebook) are skipped.

Usage:
    dlg = BulkItemImportDialog(storage_api=self.storage_api, parent=self)
    dlg.exec_()
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.bulk_item_import import ParsedItemBlock, dedupe_prefer_non_legacy, parse_bulk_items


# ── Colours ───────────────────────────────────────────────────────────────────
_WARN_BG    = "#FFF3CD"
_WARN_FG    = "#856404"
_WARN_BORD  = "#FFEEBA"
_OK_FG      = "#2d862d"
_ERR_FG     = "#cc0000"
_LEGACY_FG  = "#888888"


class _ItemRow(QWidget):
    """One row in the parsed-items list."""

    def __init__(self, block: ParsedItemBlock, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.block = block

        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(6)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.setFixedWidth(20)
        row.addWidget(self.checkbox)

        # Name
        name_text = block.name
        if block.is_legacy:
            name_text += " (legacy)"
        name_lbl = QLabel(name_text)
        name_lbl.setMinimumWidth(160)
        name_lbl.setMaximumWidth(220)
        if block.is_legacy:
            name_lbl.setStyleSheet(f"color: {_LEGACY_FG};")
        row.addWidget(name_lbl, stretch=2)

        # Type
        type_lbl = QLabel(block.data.get("item_type", "other"))
        type_lbl.setMinimumWidth(100)
        type_lbl.setMaximumWidth(140)
        type_lbl.setStyleSheet("color: #555;")
        row.addWidget(type_lbl, stretch=1)

        # Source
        source = block.data.get("source", "")
        source_lbl = QLabel(source or "—")
        source_lbl.setMinimumWidth(120)
        source_lbl.setStyleSheet("color: #555;")
        row.addWidget(source_lbl, stretch=2)

        # Status / warnings
        if block.warnings:
            warn_text = "  ".join(f"⚠ {w}" for w in block.warnings)
            status_lbl = QLabel(warn_text)
            status_lbl.setStyleSheet(f"color: {_WARN_FG}; font-size: 10px;")
        else:
            status_lbl = QLabel("✓")
            status_lbl.setStyleSheet(f"color: {_OK_FG};")
        status_lbl.setMinimumWidth(60)
        row.addWidget(status_lbl)

        self._status_lbl = status_lbl

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def mark_saved(self) -> None:
        self.checkbox.setEnabled(False)
        self._status_lbl.setText("Saved")
        self._status_lbl.setStyleSheet(f"color: {_OK_FG}; font-weight: bold;")

    def mark_error(self, msg: str) -> None:
        self._status_lbl.setText(f"✗ {msg}")
        self._status_lbl.setStyleSheet(f"color: {_ERR_FG};")


class BulkItemImportDialog(QDialog):
    """Dialog for bulk-importing D&D Beyond items via paste-and-parse."""

    def __init__(self, storage_api=None, parent=None) -> None:
        super().__init__(parent)
        self.storage_api = storage_api
        self._rows: list[_ItemRow] = []

        self.setWindowTitle("Bulk Item Import")
        self.resize(680, 640)
        self.setMinimumWidth(500)
        self.setMinimumHeight(420)

        self._build_ui()

        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(600)
        self._parse_timer.timeout.connect(self._do_parse)
        self.text_edit.textChanged.connect(self._on_text_changed)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # ---- Paste area header ----
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Paste D&D Beyond item list:"))
        hdr.addStretch()
        self._toggle_btn = QPushButton("Hide")
        self._toggle_btn.setFixedWidth(54)
        self._toggle_btn.clicked.connect(self._toggle_paste_area)
        hdr.addWidget(self._toggle_btn)
        layout.addLayout(hdr)

        # ---- Paste area ----
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Paste your D&D Beyond item list here.\n"
            "Items update automatically as you type.\n\n"
            "• Legacy items are included when no non-legacy version exists.\n"
            "• Items without full details (unowned sourcebook) are skipped."
        )
        self.text_edit.setFixedHeight(160)
        layout.addWidget(self.text_edit)

        # ---- Warning banner ----
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setStyleSheet(
            f"background:{_WARN_BG}; color:{_WARN_FG};"
            f"border:1px solid {_WARN_BORD}; padding:6px; border-radius:3px;"
        )
        self._warning.hide()
        layout.addWidget(self._warning)

        # ---- Summary label ----
        self._summary_lbl = QLabel("No items parsed yet.")
        self._summary_lbl.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(self._summary_lbl)

        # ---- Item list ----
        col_hdr = QHBoxLayout()
        col_hdr.setContentsMargins(28, 0, 0, 0)
        for label, stretch in [("Name", 2), ("Type", 1), ("Source", 2), ("Status", 0)]:
            lbl = QLabel(f"<b>{label}</b>")
            col_hdr.addWidget(lbl, stretch=stretch)
        layout.addLayout(col_hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #ccc;")
        layout.addWidget(sep)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setSpacing(2)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_container)
        layout.addWidget(self._scroll, stretch=1)

        # ---- Bottom bar ----
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setFixedWidth(80)
        self._select_all_btn.clicked.connect(self._select_all)
        self._select_all_btn.setEnabled(False)
        bottom.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton("Deselect All")
        self._deselect_all_btn.setFixedWidth(85)
        self._deselect_all_btn.clicked.connect(self._deselect_all)
        self._deselect_all_btn.setEnabled(False)
        bottom.addWidget(self._deselect_all_btn)

        bottom.addStretch()

        self._save_btn = QPushButton("Save Selected")
        self._save_btn.setEnabled(False)
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save_selected)
        bottom.addWidget(self._save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)

        layout.addLayout(bottom)

    # ── Paste area toggle ─────────────────────────────────────────────────────

    def _toggle_paste_area(self) -> None:
        visible = self.text_edit.isVisible()
        self.text_edit.setVisible(not visible)
        self._toggle_btn.setText("Show" if visible else "Hide")

    # ── Parse pipeline ────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        self._parse_timer.start()

    def _do_parse(self) -> None:
        text = self.text_edit.toPlainText().strip()
        self._clear_rows()

        if not text:
            self._summary_lbl.setText("No items parsed yet.")
            self._save_btn.setEnabled(False)
            self._select_all_btn.setEnabled(False)
            self._deselect_all_btn.setEnabled(False)
            self._warning.hide()
            return

        try:
            raw = parse_bulk_items(text, include_legacy=True)
            items = dedupe_prefer_non_legacy(raw)
        except Exception as exc:
            self._show_warning(f"Parse error: {exc}")
            self._summary_lbl.setText("Parse failed.")
            return

        self._warning.hide()

        if not items:
            self._summary_lbl.setText(
                "No items found. Make sure you paste a D&D Beyond item list "
                "with full details visible."
            )
            self._save_btn.setEnabled(False)
            self._select_all_btn.setEnabled(False)
            self._deselect_all_btn.setEnabled(False)
            return

        # Build rows
        warned = sum(1 for b in items if b.warnings)
        for block in items:
            row = _ItemRow(block, parent=self._list_container)
            self._rows.append(row)
            # Insert before the stretch
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

        n = len(items)
        legacy_count = sum(1 for b in items if b.is_legacy)
        summary_parts = [f"{n} item{'s' if n != 1 else ''} found"]
        if legacy_count:
            summary_parts.append(f"{legacy_count} legacy")
        if warned:
            summary_parts.append(f"{warned} with warnings")
        self._summary_lbl.setText("  •  ".join(summary_parts))

        self._save_btn.setEnabled(True)
        self._select_all_btn.setEnabled(True)
        self._deselect_all_btn.setEnabled(True)

        if self.text_edit.isVisible():
            self._toggle_paste_area()

    # ── Row management ────────────────────────────────────────────────────────

    def _clear_rows(self) -> None:
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

    def _select_all(self) -> None:
        for row in self._rows:
            row.checkbox.setChecked(True)

    def _deselect_all(self) -> None:
        for row in self._rows:
            row.checkbox.setChecked(False)

    # ── Warning ───────────────────────────────────────────────────────────────

    def _show_warning(self, msg: str) -> None:
        self._warning.setText(f"\u26a0  {msg}")
        self._warning.show()

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save_selected(self) -> None:
        if self.storage_api is None:
            self._show_warning(
                "Storage is not configured — items cannot be saved. "
                "Check your settings."
            )
            return

        selected = [row for row in self._rows if row.is_selected()]
        if not selected:
            self._show_warning("No items selected.")
            return

        saved = 0
        errors = 0
        for row in selected:
            block = row.block
            try:
                self.storage_api.save_item(block.key, block.data)
                row.mark_saved()
                saved += 1
            except Exception as exc:
                row.mark_error(str(exc)[:60])
                errors += 1

        parts = []
        if saved:
            parts.append(f"{saved} saved")
        if errors:
            parts.append(f"{errors} failed")
        self._summary_lbl.setText("  •  ".join(parts))
        self._summary_lbl.setStyleSheet(
            f"color: {_ERR_FG};" if errors else f"color: {_OK_FG}; font-weight: bold;"
        )

        # Disable save button if everything was saved (no un-saved rows left)
        still_pending = any(
            row.is_selected() and row.checkbox.isEnabled()
            for row in self._rows
        )
        if not still_pending:
            self._save_btn.setEnabled(False)
