import os

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSpinBox, QLineEdit, QPushButton, QLabel, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QListWidget, QListWidgetItem, QDialogButtonBox, QInputDialog
)

from app.creature import Monster

class AddCombatantWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Combatants")
        self.layout = QVBoxLayout(self)
        self.combatant_rows = []

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
        hp_input.setRange(0, 1000)  # ✅ Default to 0
        hp_input.setValue(0)

        ac_input = QSpinBox()
        ac_input.setRange(0, 50)    # ✅ Default to 0
        ac_input.setValue(0)

        spellcaster_checkbox = QCheckBox("Spellcaster")

        top_row.addWidget(QLabel("Name:"))
        top_row.addWidget(name_input)
        top_row.addWidget(QLabel("Init:"))
        top_row.addWidget(init_input)
        top_row.addWidget(QLabel("HP:"))
        top_row.addWidget(hp_input)
        top_row.addWidget(QLabel("AC:"))
        top_row.addWidget(ac_input)
        top_row.addWidget(spellcaster_checkbox)

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

        self.combatant_rows.append({
            "name": name_input,
            "init": init_input,
            "hp": hp_input,
            "ac": ac_input,
            "spellcaster": spellcaster_checkbox,
            "spell_panel": spell_panel,
            "slots": slot_inputs,
            "innate_table": innate_table
        })

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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Build Encounter")
        self.layout = QVBoxLayout(self)
        self.monster_rows = []

        title = QLabel("Build Encounter")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.layout.addWidget(title)

        # Add button
        self.add_button = QPushButton("Add Monster")
        self.add_button.clicked.connect(self.add_monster_row)
        self.layout.addWidget(self.add_button)

        # Main container
        self.monster_container = QVBoxLayout()
        self.layout.addLayout(self.monster_container)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)
        self.add_monster_row()

    def add_monster_row(self):
        row_container = QVBoxLayout()
        top_row = QHBoxLayout()

        name_input = QLineEdit()
        name_input.setPlaceholderText("Name")
        init_input = QSpinBox()
        init_input.setMaximum(100)
        hp_input = QSpinBox()
        hp_input.setMaximum(1000)
        ac_input = QSpinBox()
        ac_input.setMaximum(30)
        spellcaster_checkbox = QCheckBox("Spellcaster")
        death_saves_checkbox = QCheckBox("Death Saves")
        visible_checkbox = QCheckBox("Show")
        visible_checkbox.setchecked(True)

        top_row.addWidget(QLabel("Name:"))
        top_row.addWidget(name_input)
        top_row.addWidget(QLabel("Init:"))
        top_row.addWidget(init_input)
        top_row.addWidget(QLabel("HP:"))
        top_row.addWidget(hp_input)
        top_row.addWidget(QLabel("AC:"))
        top_row.addWidget(ac_input)
        top_row.addWidget(spellcaster_checkbox)
        top_row.addWidget(death_saves_checkbox)
        top_row.addWidget(visible_checkbox)

        # Spellcasting panel (hidden by default)
        spell_panel = QGroupBox("Spellcasting")
        spell_panel_layout = QVBoxLayout()
        spell_panel.setLayout(spell_panel_layout)
        spell_panel.setVisible(False)

        # Spell slots
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

        spellcaster_checkbox.toggled.connect(spell_panel.setVisible)

        row_container.addLayout(top_row)
        row_container.addWidget(spell_panel)
        self.monster_container.addLayout(row_container)

        self.monster_rows.append({
            "name": name_input,
            "init": init_input,
            "hp": hp_input,
            "ac": ac_input,
            "spellcaster": spellcaster_checkbox,
            "death_saves": death_saves_checkbox,
            "visible": visible_checkbox,
            "spell_panel": spell_panel,
            "slots": slot_inputs,
            "innate_table": innate_table
        })

    def get_data(self):
        monsters = []
        for row in self.monster_rows:
            name = row["name"].text().strip()
            if not name:
                continue

            monster_data = Monster(
                name=name,
                init=row["init"].value(),
                max_hp=row["hp"].value(),
                curr_hp=row["hp"].value(),
                armor_class=row["ac"].value(),
                death_saves_prompt=row["death_saves"].isChecked(),
                player_visible=row["visible"].isChecked(),
            )

            if row["spellcaster"].isChecked():
                # Gather spell slots
                spell_slots = {
                    level: box.value()
                    for level, box in row["slots"].items()
                    if box.value() > 0
                }

                # Gather innate spells
                innate_spells = {}
                table = row["innate_table"]
                for r in range(table.rowCount()):
                    spell = table.item(r, 0)
                    uses = table.item(r, 1)
                    if spell and uses:
                        spell_name = spell.text().strip()
                        try:
                            uses_value = int(uses.text())
                            if spell_name:
                                innate_spells[spell_name] = uses_value
                        except ValueError:
                            continue

                monster_data._spell_slots = spell_slots
                monster_data._innate_slots = innate_spells

            monsters.append(monster_data.to_dict())

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
