# ui/spell_import_dialog.py
"""
SpellImportDialog — paste D&D Beyond spell text, preview it, then save to storage.

Usage:
    dlg = SpellImportDialog(storage_api=self.storage_api, spell_name="Fireball", parent=self)
    if dlg.exec_() == QDialog.Accepted:
        key, data = dlg.saved_key, dlg.saved_data
"""
from __future__ import annotations

import re
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSizePolicy, QTextBrowser,
)

from app.spell_parser import parse_spell, validate_spell, spell_key


# ── Colours — D&D Beyond spell card palette ───────────────────────────────────
_BG       = "#FAFAFA"   # near-white card background
_TITLE    = "#1a1a1a"   # spell name
_CONC     = "#1a5fa8"   # concentration ◆ diamond (blue)
_HDR      = "#555555"   # property column header labels
_TEXT     = "#1a1a1a"   # body text
_DIVIDER  = "#d0d0d0"   # horizontal / vertical rules
_NOTE     = "#666666"   # footnote text
_CONC_SYM = "\u25C6"    # ◆

_ORDINALS = {0: "Cantrip", 1: "1st", 2: "2nd", 3: "3rd",
             4: "4th", 5: "5th", 6: "6th", 7: "7th", 8: "8th", 9: "9th"}


class SpellImportDialog(QDialog):
    """Dialog for importing a D&D Beyond spell via paste-and-parse."""

    def __init__(
        self,
        storage_api=None,
        spell_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.storage_api = storage_api
        self._spell_name_hint = spell_name

        self._parsed_data: Optional[dict] = None
        self.saved_key:  Optional[str]  = None
        self.saved_data: Optional[dict] = None

        self.setWindowTitle(f"Import Spell{': ' + spell_name if spell_name else ''}")
        self.resize(460, 680)
        self.setMinimumWidth(380)
        self.setMinimumHeight(420)

        self._build_ui()

        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(500)
        self._parse_timer.timeout.connect(self._do_parse)

        self.text_edit.textChanged.connect(self._on_text_changed)

    # ── Layout ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)

        # Text input header
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Paste D&D Beyond spell text:"))
        header_row.addStretch()
        self._toggle_btn = QPushButton("Hide")
        self._toggle_btn.setFixedWidth(54)
        self._toggle_btn.clicked.connect(self._toggle_text_panel)
        header_row.addWidget(self._toggle_btn)
        layout.addLayout(header_row)

        # Text input
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Paste your D&D Beyond spell text here…\n"
            "The preview updates automatically after you stop typing."
        )
        self.text_edit.setFixedHeight(130)
        layout.addWidget(self.text_edit)

        # Warning banner
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._warning.setStyleSheet(
            "background:#FFF3CD; color:#856404;"
            "border:1px solid #FFEEBA; padding:6px; border-radius:3px;"
        )
        self._warning.hide()
        layout.addWidget(self._warning)

        # Preview
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setStyleSheet(f"background:{_BG}; border:1px solid {_DIVIDER};")
        self._show_placeholder()
        layout.addWidget(self.preview, stretch=1)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addWidget(QLabel("Spell name:"))
        self.name_edit = QLineEdit()
        if self._spell_name_hint:
            self.name_edit.setText(self._spell_name_hint)
        self.name_edit.setPlaceholderText("e.g. Fireball")
        self.name_edit.setToolTip("Overrides the parsed name. Determines the storage key.")
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

    # ── Text panel toggle ─────────────────────────────────────────────

    def _toggle_text_panel(self) -> None:
        visible = self.text_edit.isVisible()
        self.text_edit.setVisible(not visible)
        self._toggle_btn.setText("Show" if visible else "Hide")

    # ── Parse pipeline ────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        self._parse_timer.start()

    def _do_parse(self) -> None:
        text = self.text_edit.toPlainText().strip()

        if not text:
            self._parsed_data = None
            self._show_placeholder()
            self._warning.hide()
            self._save_btn.setEnabled(False)
            return

        try:
            data = parse_spell(text)
        except Exception as exc:
            self._show_warning(f"Parse error: {exc}")
            self._parsed_data = None
            self._save_btn.setEnabled(False)
            return

        self._parsed_data = data

        warnings = validate_spell(data)
        if warnings:
            self._show_warning("  •  ".join(warnings))
        else:
            self._warning.hide()

        self.preview.setHtml(self._build_preview_html(data))

        parsed_name = data.get("name", "")
        if parsed_name and not self.name_edit.text().strip():
            self.name_edit.setText(parsed_name)

        self._save_btn.setEnabled(True)

        if self.text_edit.isVisible():
            self._toggle_text_panel()

    def _show_warning(self, message: str) -> None:
        self._warning.setText(f"\u26a0  {message}")
        self._warning.show()

    def _show_placeholder(self) -> None:
        self.preview.setHtml(
            f'<body style="background:{_BG}; color:#999; '
            f'font-family:&quot;Segoe UI&quot;,Arial,sans-serif;">'
            f'<p style="margin:20px; text-align:center; font-style:italic;">'
            f'No spell loaded.</p></body>'
        )

    # ── Preview HTML ──────────────────────────────────────────────────

    def _build_preview_html(self, data: dict) -> str:
        p: list[str] = []

        font = "font-family:&quot;Segoe UI&quot;,Arial,sans-serif;"
        p.append(
            f'<html><body style="background-color:{_BG}; {font} '
            f'font-size:13px; color:{_TEXT}; margin:10px;">'
        )

        # ── Title ─────────────────────────────────────────────────────
        name = data.get("name", "Unknown")
        conc = data.get("concentration", False)
        conc_badge = (
            f' <span style="color:{_CONC}; font-size:14px;">{_CONC_SYM}</span>'
            if conc else ""
        )
        p.append(
            f'<table width="100%" style="border-collapse:collapse;">'
            f'<tr><td style="font-size:20px; font-weight:bold; color:{_TITLE}; '
            f'border-bottom:1px solid {_DIVIDER}; padding-bottom:6px;">'
            f'{name}{conc_badge}</td></tr></table>'
        )

        # ── Property grid ─────────────────────────────────────────────
        # Row 1: LEVEL | CASTING TIME | RANGE/AREA | COMPONENTS
        # Row 2: DURATION | SCHOOL | ATTACK/SAVE | DAMAGE/EFFECT
        level = data.get("level", 0)
        level_str = _ORDINALS.get(level, f"{level}th")

        dur_val = data.get("duration", "")
        dur_display = (
            f'<span style="color:{_CONC};">{_CONC_SYM}</span> {dur_val}'
            if conc else dur_val
        )

        sep   = f'border-right:1px solid {_DIVIDER};'
        hd    = f'font-size:9px; font-weight:bold; color:{_HDR};'
        pad_l = 'padding:6px 8px 4px 0;'
        pad_m = f'padding:6px 8px 4px 8px;'
        pad_r = 'padding:6px 0 4px 8px;'

        def _cell(label: str, value: str, extra_style: str = "", value_html: str = "") -> str:
            disp = value_html if value_html else value
            return (
                f'<td style="{extra_style}">'
                f'<span style="{hd}">{label}</span><br>'
                f'{disp}'
                f'</td>'
            )

        p.append(
            f'<table width="100%" style="border-collapse:collapse; margin-top:6px;">'
            # Row 1 — labels + values
            f'<tr style="border-bottom:1px solid {_DIVIDER};">'
            + _cell("LEVEL",        level_str,                   sep + pad_l)
            + _cell("CASTING TIME", data.get("casting_time",""), sep + pad_m)
            + _cell("RANGE/AREA",   data.get("range",""),        sep + pad_m)
            + _cell("COMPONENTS",   data.get("components",""),       pad_r)
            + f'</tr>'
            # Row 2 — labels + values
            f'<tr>'
            + _cell("DURATION",      dur_val, sep + pad_l, value_html=dur_display)
            + _cell("SCHOOL",        data.get("school",""),        sep + pad_m)
            + _cell("ATTACK/SAVE",   data.get("attack_save",""),   sep + pad_m)
            + _cell("DAMAGE/EFFECT", data.get("damage_effect",""),     pad_r)
            + f'</tr>'
            f'</table>'
        )

        # ── Divider ───────────────────────────────────────────────────
        p.append(f'<hr style="border:none; border-top:1px solid {_DIVIDER}; margin:8px 0;">')

        # ── Description ───────────────────────────────────────────────
        desc = data.get("description", "")
        if desc:
            for para in desc.split("\n\n"):
                para = para.strip().replace("\n", "<br>")
                if para:
                    p.append(f'<p style="margin:4px 0; line-height:1.4;">{para}</p>')

        # ── Footnotes ─────────────────────────────────────────────────
        for note in data.get("footnotes", []):
            p.append(
                f'<p style="margin:6px 0 0 0; font-size:10px; '
                f'color:{_NOTE}; font-style:italic;">{note}</p>'
            )

        p.append('</body></html>')
        return "".join(p)

    # ── Save ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._parsed_data is None:
            return

        name = self.name_edit.text().strip()
        if not name:
            self._show_warning("Enter a spell name before saving.")
            return

        key = spell_key(name)

        if self.storage_api is None:
            self._show_warning(
                "Storage API is not configured — spell cannot be saved remotely."
            )
            return

        # Update the name in data to match the (possibly overridden) field
        save_data = dict(self._parsed_data)
        save_data["name"] = name

        try:
            self.storage_api.save_spell(key, save_data)
        except Exception as exc:
            self._show_warning(f"Save failed: {exc}")
            return

        self.saved_key  = key
        self.saved_data = save_data
        self.accept()
