import os
import re

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSpinBox, QLineEdit, QPushButton, QLabel, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QListWidget, QListWidgetItem, QDialogButtonBox, QInputDialog,
    QTextEdit, QScrollArea, QWidget,
)

from app.creature import Monster


# ── Shared statblock auto-fill helper ───────────────────────────────

def _apply_statblock_to_row(row: dict, data: dict) -> None:
    """Populate a dialog row's input fields from a parsed statblock dict.

    Only sets fields that have a non-zero / non-None value in the statblock
    so blank statblocks don't silently zero out user-entered values.
    """
    hp = data.get("hit_points", {})
    if hp.get("average"):
        row["hp"].setValue(hp["average"])

    ac_list = data.get("armor_class", [])
    if ac_list and ac_list[0].get("value"):
        row["ac"].setValue(ac_list[0]["value"])

    init_bonus = data.get("initiative_bonus")
    if init_bonus is not None and "init" in row:
        row["init"].setValue(init_bonus)

    sc = data.get("spellcasting")
    if sc:
        row["spellcaster"].setChecked(True)

        for level_str, count in sc.get("slots", {}).items():
            try:
                level = int(level_str)
                if level in row["slots"] and count:
                    row["slots"][level].setValue(count)
            except (ValueError, KeyError):
                pass

        # Populate innate spells table (clear first to avoid duplication)
        table = row["innate_table"]
        table.setRowCount(0)
        for key, spells in sc.get("innate", {}).items():
            uses = 0 if key == "at_will" else int(
                m.group(1)) if (m := re.match(r'(\d+)_per_day', key)) else 1
            for spell in spells:
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(spell.title()))
                table.setItem(r, 1, QTableWidgetItem(str(uses)))

    row["_statblock_data"] = data

    if "autofill_label" in row:
        row["autofill_label"].setVisible(True)

class AddCombatantWindow(QDialog):
    def __init__(self, parent=None, statblock_lookup=None):
        super().__init__(parent)
        self.setWindowTitle("Add Combatants")
        self.layout = QVBoxLayout(self)
        self.combatant_rows = []
        self._statblock_lookup = statblock_lookup

        title = QLabel("Add Combatants")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.layout.addWidget(title)

        self.add_button = QPushButton("Add Combatant")
        self.add_button.clicked.connect(self.add_row)
        self.layout.addWidget(self.add_button)

        self.combatant_container = QVBoxLayout()
        self.layout.addLayout(self.combatant_container)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

        for _ in range(5):  # Start with 5 rows
            self.add_row()

    def add_row(self):
        row_container = QVBoxLayout()
        top_row = QHBoxLayout()

        name_input = QLineEdit()
        init_input = QSpinBox()
        init_input.setRange(-99, 99)

        hp_input = QSpinBox()
        hp_input.setRange(0, 1000)
        hp_input.setValue(0)

        ac_input = QSpinBox()
        ac_input.setRange(0, 50)
        ac_input.setValue(0)

        spellcaster_checkbox = QCheckBox("Spellcaster")

        autofill_label = QLabel("✓ Auto-filled from statblock")
        autofill_label.setStyleSheet(
            "color: #5a8a5a; font-size: 10px; font-style: italic;"
        )
        autofill_label.setVisible(False)

        top_row.addWidget(QLabel("Name:"))
        top_row.addWidget(name_input)
        top_row.addWidget(QLabel("Init:"))
        top_row.addWidget(init_input)
        top_row.addWidget(QLabel("HP:"))
        top_row.addWidget(hp_input)
        top_row.addWidget(QLabel("AC:"))
        top_row.addWidget(ac_input)
        top_row.addWidget(spellcaster_checkbox)
        top_row.addWidget(autofill_label)

        # === Spellcasting Panel (Hidden by Default)
        spell_panel = QGroupBox("Spellcasting")
        spell_panel_layout = QVBoxLayout()
        spell_panel.setLayout(spell_panel_layout)
        spell_panel.setVisible(False)

        # Spell slots 1–9
        slot_inputs = {}
        slot_form = QFormLayout()
        for level in range(1, 10):
            box = QSpinBox()
            box.setMaximum(10)
            slot_inputs[level] = box
            slot_form.addRow(f"Level {level} Slots:", box)
        spell_panel_layout.addLayout(slot_form)

        # Innate spells table
        innate_table = QTableWidget(0, 2)
        innate_table.setHorizontalHeaderLabels(["Spell Name", "Uses"])
        innate_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        spell_panel_layout.addWidget(QLabel("Innate Spells:"))
        spell_panel_layout.addWidget(innate_table)

        add_innate_button = QPushButton("+ Add Innate Spell")
        def add_innate_row():
            row = innate_table.rowCount()
            innate_table.insertRow(row)
            innate_table.setItem(row, 0, QTableWidgetItem(""))
            innate_table.setItem(row, 1, QTableWidgetItem("1"))
        add_innate_button.clicked.connect(add_innate_row)
        spell_panel_layout.addWidget(add_innate_button)

        # Show/hide spellcasting panel
        spellcaster_checkbox.toggled.connect(spell_panel.setVisible)

        # Pack row
        row_container.addLayout(top_row)
        row_container.addWidget(spell_panel)
        self.combatant_container.addLayout(row_container)

        row_dict = {
            "name": name_input,
            "init": init_input,
            "hp": hp_input,
            "ac": ac_input,
            "spellcaster": spellcaster_checkbox,
            "spell_panel": spell_panel,
            "slots": slot_inputs,
            "innate_table": innate_table,
            "autofill_label": autofill_label,
        }
        self.combatant_rows.append(row_dict)

        if self._statblock_lookup:
            def _on_name_done(rd=row_dict):
                name = rd["name"].text().strip()
                if not name:
                    return
                data = self._statblock_lookup(name)
                if data:
                    _apply_statblock_to_row(rd, data)
            name_input.editingFinished.connect(_on_name_done)

    def get_data(self):
        data = []
        for row in self.combatant_rows:
            name = row["name"].text().strip()
            if not name:
                continue

            creature = {
                "Name": name,
                "Init": row["init"].value(),
                "HP": row["hp"].value(),
                "AC": row["ac"].value()
            }

            if row["spellcaster"].isChecked():
                # Add spell slots
                spell_slots = {
                    level: box.value()
                    for level, box in row["slots"].items()
                    if box.value() > 0
                }
                if spell_slots:
                    creature["_spell_slots"] = spell_slots

                # Add innate spells
                innate_spells = {}
                table = row["innate_table"]
                for r in range(table.rowCount()):
                    spell_item = table.item(r, 0)
                    uses_item = table.item(r, 1)
                    if spell_item and uses_item:
                        try:
                            spell_name = spell_item.text().strip()
                            uses = int(uses_item.text())
                            if spell_name:
                                innate_spells[spell_name] = uses
                        except ValueError:
                            continue
                if innate_spells:
                    creature["_innate_slots"] = innate_spells

            from app.statblock_parser import extract_limited_abilities
            ability_uses = extract_limited_abilities(row.get("_statblock_data") or {})
            if ability_uses:
                creature["_ability_uses"] = ability_uses

            data.append(creature)

        return data


class RemoveCombatantWindow(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remove Combatants")
        self.manager = manager
        self.rmv_layout = QVBoxLayout()

        title = QLabel("Remove Combatants")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.rmv_layout.addWidget(title)

        self.rmv_list = QListWidget(self)
        self.rmv_list.setSelectionMode(QListWidget.MultiSelection)

        for creature in self.manager.creatures.values():
            item = QListWidgetItem(creature.name)
            self.rmv_list.addItem(item)

        self.rmv_layout.addWidget(self.rmv_list, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.rmv_layout.addWidget(self.button_box, 2)
        self.setLayout(self.rmv_layout)

    def get_selected_creatures(self):
        selected_items = self.rmv_list.selectedItems()
        return [item.text() for item in selected_items]



class BuildEncounterWindow(QDialog):
    def __init__(self, parent=None, storage_api=None):
        super().__init__(parent)
        self.setWindowTitle("Build Encounter")
        self.setMinimumWidth(620)
        self._storage_api = storage_api
        self.roster_rows: list[dict] = []
        self._display_key_map: dict[str, str] = {}

        root = QVBoxLayout(self)

        # ── Available Statblocks ──────────────────────────────────────
        browser_group = QGroupBox("Available Statblocks")
        browser_layout = QVBoxLayout(browser_group)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter…")
        self._search.textChanged.connect(self._filter_list)
        browser_layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setMaximumHeight(200)
        self._list.itemDoubleClicked.connect(lambda _: self._add_selected(self._qty.value()))
        browser_layout.addWidget(self._list)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Qty:"))
        self._qty = QSpinBox()
        self._qty.setRange(1, 20)
        self._qty.setValue(1)
        add_row.addWidget(self._qty)
        add_btn = QPushButton("Add to Encounter")
        add_btn.clicked.connect(lambda: self._add_selected(self._qty.value()))
        add_row.addWidget(add_btn)
        add_row.addStretch()
        browser_layout.addLayout(add_row)

        root.addWidget(browser_group)

        # ── Encounter Roster ──────────────────────────────────────────
        roster_group = QGroupBox("Encounter Roster")
        roster_outer = QVBoxLayout(roster_group)

        header_row = QHBoxLayout()
        name_hdr = QLabel("Name")
        name_hdr.setStyleSheet("font-weight: bold;")
        header_row.addWidget(name_hdr, 3)
        for hdr_text in ("Init", "Max HP", "AC", ""):
            lbl = QLabel(hdr_text)
            lbl.setStyleSheet("font-weight: bold;")
            header_row.addWidget(lbl)
        roster_outer.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        self._roster_widget = QWidget()
        self._roster_layout = QVBoxLayout(self._roster_widget)
        self._roster_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self._roster_widget)
        roster_outer.addWidget(scroll)

        root.addWidget(roster_group)

        # ── Buttons ───────────────────────────────────────────────────
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

        self._populate_list()

    def _populate_list(self):
        if not self._storage_api:
            placeholder = QListWidgetItem("(No storage API configured)")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsEnabled)
            self._list.addItem(placeholder)
            return
        try:
            keys = self._storage_api.list_statblock_keys()
        except Exception:
            keys = []
        if not keys:
            placeholder = QListWidgetItem("(No statblocks found)")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsEnabled)
            self._list.addItem(placeholder)
            return
        for key in sorted(keys):
            display = key.removesuffix(".json").replace("_", " ").title()
            self._display_key_map[display] = key
            self._list.addItem(display)

    def _filter_list(self, text: str):
        text = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(text not in item.text().lower())

    def _add_selected(self, qty: int):
        selected = self._list.selectedItems()
        if not selected:
            return
        display_name = selected[0].text()
        key = self._display_key_map.get(display_name)
        if not key:
            return
        try:
            data = self._storage_api.get_statblock(key) or {}
        except Exception:
            data = {}

        default_hp = data.get("hit_points", {}).get("average", 0)
        ac_list = data.get("armor_class") or [{}]
        default_ac = ac_list[0].get("value", 0)

        if qty > 1:
            for i in range(1, qty + 1):
                self._add_roster_row(f"{display_name} {i}", data, default_hp, default_ac)
        else:
            self._add_roster_row(display_name, data, default_hp, default_ac)

    def _add_roster_row(self, name: str, statblock_data: dict, default_hp: int, default_ac: int):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 2)

        name_lbl = QLabel(name)
        name_lbl.setWordWrap(True)
        row_layout.addWidget(name_lbl, 3)

        init_spin = QSpinBox()
        init_spin.setRange(-20, 30)
        init_spin.setValue(0)
        init_spin.setFixedWidth(55)
        row_layout.addWidget(init_spin)

        hp_spin = QSpinBox()
        hp_spin.setRange(0, 9999)
        hp_spin.setValue(default_hp)
        hp_spin.setFixedWidth(70)
        row_layout.addWidget(hp_spin)

        ac_spin = QSpinBox()
        ac_spin.setRange(0, 30)
        ac_spin.setValue(default_ac)
        ac_spin.setFixedWidth(55)
        row_layout.addWidget(ac_spin)

        remove_btn = QPushButton("×")
        remove_btn.setFixedWidth(28)
        row_layout.addWidget(remove_btn)

        row_dict = {
            "widget": row_widget,
            "name": name,
            "statblock_data": statblock_data,
            "init": init_spin,
            "hp": hp_spin,
            "ac": ac_spin,
        }
        self.roster_rows.append(row_dict)
        self._roster_layout.addWidget(row_widget)

        def _remove(rd=row_dict):
            rd["widget"].setParent(None)
            rd["widget"].deleteLater()
            self.roster_rows.remove(rd)
        remove_btn.clicked.connect(_remove)

    def get_data(self) -> list:
        from app.statblock_parser import extract_limited_abilities
        monsters = []
        for row in self.roster_rows:
            data = row["statblock_data"] or {}
            monster = Monster(
                name=row["name"],
                init=row["init"].value(),
                max_hp=row["hp"].value(),
                curr_hp=row["hp"].value(),
                armor_class=row["ac"].value(),
            )
            sc = data.get("spellcasting")
            if sc:
                monster._spell_slots = {
                    int(k): v for k, v in sc.get("slots", {}).items() if v
                }
                innate: dict[str, int] = {}
                for key, spells in sc.get("innate", {}).items():
                    if key == "at_will":
                        uses = -1
                    elif m := re.match(r'(\d+)_per_day', key):
                        uses = int(m.group(1))
                    else:
                        uses = 1
                    for spell in spells:
                        innate[spell.title()] = uses
                monster._innate_slots = innate
            monster._ability_uses = extract_limited_abilities(data)
            monsters.append(monster.to_dict())
        return monsters

    def get_metadata(self) -> dict:
        filename, ok = QInputDialog.getText(self, "Save Encounter As", "Enter filename:")
        if not ok or not filename.strip():
            return {}

        description, _ = QInputDialog.getText(self, "Description", "Enter description (optional):")

        return {
            "filename": filename.strip().replace(" ", "_"),
            "description": description.strip()
        }


class LoadEncounterWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Encounter")
        self.selected_file = None
        self.load_layout = QVBoxLayout()

        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.on_item_clicked)
        self.populate_file_list()

        self.load_button = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel, self)
        self.load_button.accepted.connect(self.accept)
        self.load_button.rejected.connect(self.reject)

        self.load_layout.addWidget(self.file_list)
        self.load_layout.addWidget(self.load_button)

        self.setLayout(self.load_layout)

    def on_item_clicked(self, item):
        self.selected_file = item.text().replace(' ','_')

    def get_data_dict(self):
        return os.path.join(self.get_parent_dir(), 'data')

    def get_data_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'data', filename)
    
    def get_parent_dir(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))


class MergeEncounterWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merger Encounter")
        self.selected_file = None
        self.merge_layout = QVBoxLayout()

        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.on_item_clicked)
        self.populate_file_list()

        self.merge_button = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel, self)
        self.merge_button.accepted.connect(self.accept)
        self.merge_button.rejected.connect(self.reject)

        self.merge_layout.addWidget(self.file_list)
        self.merge_layout.addWidget(self.merge_button)

        self.setLayout(self.merge_layout)

    def on_item_clicked(self, item):
        self.selected_file = item.text().replace(' ','_')

    def get_data_dict(self):
        return os.path.join(self.get_parent_dir(), 'data')

    def get_data_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'data', filename)
    
    def get_parent_dir(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))


class UpdatePlayerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Player Stats")
        self.update_layout = QVBoxLayout()

        title = QLabel("Update Player Stats")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.update_layout.addWidget(title)

        # Custom Table Widget
        self.player_table = QTableWidget()

        self.decision_buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.decision_buttons.accepted.connect(self.accept)
        self.decision_buttons.rejected.connect(self.reject)
        
        self.update_layout.addWidget(self.player_table)
        self.update_layout.addWidget(self.decision_buttons)
        self.setLayout(self.update_layout)
    
    def resize_table(self):
        total_width = self.player_table.verticalHeader().width()
        for column in range(self.player_table.columnCount()):
            self.player_table.resizeColumnToContents(column)
            total_width += self.player_table.columnWidth(column)

        total_height = self.player_table.horizontalHeader().height()
        for row in range(self.player_table.rowCount()):
            self.player_table.resizeRowToContents(row)
            total_height += self.player_table.rowHeight(row)

        self.player_table.setFixedWidth(total_width + self.player_table.frameWidth() * 2)
        self.player_table.setFixedHeight(total_height + self.player_table.frameWidth() * 2)


class LairActionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Lair Action")
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_input = QLineEdit("Lair Action")
        form.addRow("Name:", self.name_input)

        self.init_input = QSpinBox()
        self.init_input.setRange(1, 30)
        self.init_input.setValue(20)
        form.addRow("Initiative:", self.init_input)

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Optional notes shown when this turn is reached...")
        self.notes_input.setFixedHeight(80)
        form.addRow("Notes:", self.notes_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return (
            self.name_input.text().strip() or "Lair Action",
            self.init_input.value(),
            self.notes_input.toPlainText().strip(),
        )
