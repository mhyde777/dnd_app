# ui/item_import_dialog.py
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSizePolicy, QFormLayout, QWidget,
    QScrollArea,
)

from app.item_parser import parse_item, validate_item, item_key


class ItemImportDialog(QDialog):
    """
    Dialog for importing a D&D Beyond item via paste-and-parse.

    After a successful save, `saved_key` and `saved_data` hold the stored
    key (e.g. "longsword.json") and the parsed dict respectively.
    """

    def __init__(self, storage_api=None, parent=None):
        super().__init__(parent)
        self.storage_api = storage_api

        self._parsed_data: Optional[dict] = None
        self.saved_key:  Optional[str]  = None
        self.saved_data: Optional[dict] = None

        self.setWindowTitle("Import Item")
        self.resize(480, 720)
        self.setMinimumWidth(420)
        self.setMinimumHeight(480)

        self._build_ui()

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
        header_row.addWidget(QLabel("Paste D&D Beyond item text:"))
        header_row.addStretch()
        self._toggle_btn = QPushButton("Hide")
        self._toggle_btn.setFixedWidth(54)
        self._toggle_btn.clicked.connect(self._toggle_text_panel)
        header_row.addWidget(self._toggle_btn)
        layout.addLayout(header_row)

        # ---- Text input ----
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Paste your D&D Beyond item text here…\n"
            "The preview updates automatically after you stop typing."
        )
        self.text_edit.setFixedHeight(150)
        layout.addWidget(self.text_edit)

        # ---- Warning banner ----
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._warning.setStyleSheet(
            "background:#FFF3CD; color:#856404;"
            "border:1px solid #FFEEBA; padding:6px; border-radius:3px;"
        )
        self._warning.hide()
        layout.addWidget(self._warning)

        # ---- Live preview (scrollable form) ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        preview_container = QWidget()
        form = QFormLayout(preview_container)
        form.setSpacing(4)
        form.setContentsMargins(4, 4, 4, 4)

        def _field_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-weight: bold;")
            return lbl

        def _value_label() -> QLabel:
            lbl = QLabel()
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return lbl

        self._lv_name        = _value_label()
        self._lv_type        = _value_label()
        self._lv_subtype     = _value_label()
        self._lv_rarity      = _value_label()
        self._lv_attunement  = _value_label()
        self._lv_cost        = _value_label()
        self._lv_weight      = _value_label()
        self._lv_properties  = _value_label()
        self._lv_damage_ac   = _value_label()
        self._lv_auto_tags   = _value_label()
        self._lv_description = _value_label()

        form.addRow(_field_label("Name:"),        self._lv_name)
        form.addRow(_field_label("Type:"),        self._lv_type)
        form.addRow(_field_label("Subtype:"),     self._lv_subtype)
        form.addRow(_field_label("Rarity:"),      self._lv_rarity)
        form.addRow(_field_label("Attunement:"),  self._lv_attunement)
        form.addRow(_field_label("Cost:"),        self._lv_cost)
        form.addRow(_field_label("Weight:"),      self._lv_weight)
        form.addRow(_field_label("Properties:"),  self._lv_properties)
        form.addRow(_field_label("Damage / AC:"), self._lv_damage_ac)
        form.addRow(_field_label("Auto-tags:"),   self._lv_auto_tags)
        form.addRow(_field_label("Description:"), self._lv_description)

        scroll.setWidget(preview_container)
        layout.addWidget(scroll, stretch=1)

        # ---- Custom tags editor ----
        tags_row = QHBoxLayout()
        tags_row.addWidget(QLabel("Custom tags (comma-separated):"))
        self._custom_tags_edit = QLineEdit()
        self._custom_tags_edit.setPlaceholderText("e.g. shop_stock, players_loot")
        tags_row.addWidget(self._custom_tags_edit, stretch=1)
        layout.addLayout(tags_row)

        # ---- Bottom bar ----
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addWidget(QLabel("Item name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Longsword")
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

    # ── Toggle text panel ─────────────────────────────────────────────

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
            self._clear_preview()
            self._warning.hide()
            self._save_btn.setEnabled(False)
            return

        try:
            data = parse_item(text)
        except Exception as exc:
            self._show_warning(f"Parse error: {exc}")
            self._parsed_data = None
            self._save_btn.setEnabled(False)
            return

        self._parsed_data = data

        warnings = validate_item(data)
        if warnings:
            self._show_warning("  •  ".join(warnings))
        else:
            self._warning.hide()

        self._update_preview(data)

        parsed_name = data.get("name", "")
        if parsed_name and not self.name_edit.text().strip():
            self.name_edit.setText(parsed_name)

        self._save_btn.setEnabled(True)

        if self.text_edit.isVisible():
            self._toggle_text_panel()

    def _show_warning(self, message: str) -> None:
        self._warning.setText(f"\u26a0  {message}")
        self._warning.show()

    def _clear_preview(self) -> None:
        for lbl in (
            self._lv_name, self._lv_type, self._lv_subtype, self._lv_rarity,
            self._lv_attunement, self._lv_cost, self._lv_weight,
            self._lv_properties, self._lv_damage_ac, self._lv_auto_tags,
            self._lv_description,
        ):
            lbl.setText("")

    def _update_preview(self, data: dict) -> None:
        self._lv_name.setText(data.get("name", ""))
        self._lv_type.setText(data.get("item_type", ""))
        self._lv_subtype.setText(data.get("subtype", "") or "—")
        self._lv_rarity.setText(data.get("rarity", "") or "—")

        att = data.get("requires_attunement", False)
        if att is False:
            att_text = "No"
        elif att is True:
            att_text = "Yes"
        else:
            att_text = str(att)
        self._lv_attunement.setText(att_text)

        cost = data.get("cost", "")
        cost_gp = data.get("cost_gp", 0.0)
        if cost:
            self._lv_cost.setText(f"{cost} ({cost_gp} gp)" if cost_gp else cost)
        else:
            self._lv_cost.setText("—")

        weight = data.get("weight", 0.0)
        self._lv_weight.setText(f"{weight} lb." if weight else "—")

        props = data.get("properties", [])
        self._lv_properties.setText(", ".join(props) if props else "—")

        damage = data.get("damage", "")
        ac = data.get("ac", "")
        if damage and ac:
            self._lv_damage_ac.setText(f"Damage: {damage}  /  AC: {ac}")
        elif damage:
            self._lv_damage_ac.setText(f"Damage: {damage}")
        elif ac:
            self._lv_damage_ac.setText(f"AC: {ac}")
        else:
            self._lv_damage_ac.setText("—")

        tags = data.get("tags", [])
        self._lv_auto_tags.setText(", ".join(tags) if tags else "—")

        desc = data.get("description", "")
        self._lv_description.setText(desc[:200] + ("…" if len(desc) > 200 else "") if desc else "—")

    # ── Save ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._parsed_data is None:
            return

        name = self.name_edit.text().strip()
        if not name:
            self._show_warning("Enter an item name before saving.")
            return

        key = item_key(name)

        if self.storage_api is None:
            self._show_warning(
                "Storage API is not configured — item cannot be saved remotely. "
                "Connect to a storage server in settings."
            )
            return

        # Merge auto-tags with custom tags
        auto_tags: list[str] = list(self._parsed_data.get("tags", []))
        custom_raw = self._custom_tags_edit.text().strip()
        custom_tags = [t.strip().lower() for t in custom_raw.split(",") if t.strip()]
        merged_tags = list(dict.fromkeys(auto_tags + custom_tags))  # deduplicate, preserve order

        data = dict(self._parsed_data)
        data["name"] = name
        data["tags"] = merged_tags

        try:
            self.storage_api.save_item(key, data)
        except Exception as exc:
            self._show_warning(f"Save failed: {exc}")
            return

        self.saved_key  = key
        self.saved_data = data

        self.accept()
