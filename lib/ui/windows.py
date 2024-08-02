from typing import List, Dict, Any
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QDialogButtonBox, QListWidget, QListWidgetItem,
    QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel, QItemDelegate,
    QTableWidgetItem
)
from PyQt5.QtCore import Qt
from app.manager import CreatureManager
from app.creature import I_Creature
import os, json

# class CustomTableWidget(QTableWidget):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.setEditTriggers(QTableWidget.AllEditTriggers)
#         self.setItemDelegate(CustomItemDelegate(self))
#
#     def editNext(self):
#         current_row = self.currentRow()
#         current_col = self.currentColumn()
#         row_count = self.rowCount()
#         col_count = self.columnCount()
#
#         if current_row == row_count - 1 and current_col == col_count - 1:
#             self.insertRow(row_count)
#             for col in range(col_count):
#                 self.setItem(row_count, col, QTableWidgetItem(""))
#
#         super().editNext()
#
# class CustomItemDelegate(QItemDelegate):
#     def __init__(self, parent=None):
#         super().__init__(parent)
#
#     def createEditor(self, parent, option, index):
#         return QLineEdit(parent)


class AddCombatantWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Combatants")

        self.add_layout = QVBoxLayout()

        self.add_table = QTableWidget(self)
        self.add_table.setRowCount(5)
        self.add_table.setColumnCount(4)
        self.add_table.setHorizontalHeaderLabels(['Name', 'Init', 'HP', 'AC'])

        self.add_layout.addWidget(self.add_table, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.add_layout.addWidget(self.button_box, 2)
        self.setLayout(self.add_layout)
        self.resize(self.add_table.sizeHint().width() + 185, self.sizeHint().height())

    def get_data(self):
        data: List[Dict[str, Any]] = []
        for row in range(self.add_table.rowCount()):
            name = self.add_table.item(row, 0)
            init = self.add_table.item(row, 1)
            hp = self.add_table.item(row, 2)
            ac = self.add_table.item(row, 3)
            if name and init and hp and ac:
                data.append({
                    'Name': name.text(),
                    'Init': int(init.text()),
                    'HP': int(hp.text()),
                    'AC': int(ac.text())
                })
        return data


class RemoveCombatantWindow(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remove Combatants")
        self.manager = manager
        self.rmv_layout = QVBoxLayout()

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
        self.builder_layout = QVBoxLayout()
        
        # Custom Table Widget
        self.encounter_table = QTableWidget(21, 4)
        self.encounter_table.setHorizontalHeaderLabels(["Name", "Initiative", "HP", "AC"])

        self.filename_input = QLineEdit(self)
        self.save_button = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.save_button.accepted.connect(self.accept)
        self.save_button.rejected.connect(self.reject)

        self.builder_layout.addWidget(self.filename_input, 1)
        self.builder_layout.addWidget(self.encounter_table, 2)
        self.builder_layout.addWidget(self.save_button, 3)

        self.setLayout(self.builder_layout)
        self.resize(self.encounter_table.sizeHint().width() + 183, self.sizeHint().height())


    def get_data(self):
        data: List[Dict[str, Any]] = []
        for row in range(self.encounter_table.rowCount()):
            name = self.encounter_table.item(row, 0)
            init = self.encounter_table.item(row, 1)
            hp = self.encounter_table.item(row, 2)
            ac = self.encounter_table.item(row, 3)
            if name and init and hp and ac:
                data.append({
                    'Name': name.text(),
                    'Init': int(init.text()),
                    'HP': int(hp.text()),
                    'AC': int(ac.text())
                })
        return data


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

    def populate_file_list(self):
        exceptions = {'players', 'last_state'}
        try:
            files = os.listdir(self.get_data_dict())
        except FileNotFoundError:
            print(f'Directory {self.get_data_path()} not found.')
            return

        for file in files:
            name, ext = os.path.splitext(file)
            if name not in exceptions and os.path.isfile(self.get_data_path(file)):
                name = name.replace('_', ' ')
                self.file_list.addItem(name)

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
        self.setWindowTitle('Update Player Stats')

        self.layout = QVBoxLayout()

        self.player_table = QTableWidget()
        self.layout.addWidget(self.player_table)

        self.decision_buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.decision_buttons.accepted.connect(self.accept)
        self.decision_buttons.rejected.connect(self.reject)
