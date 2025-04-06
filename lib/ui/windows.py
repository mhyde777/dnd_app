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
from app.gist_utils import list_gists

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
        
        # Table Widget
        self.encounter_table = QTableWidget(21, 4)
        self.encounter_table.setHorizontalHeaderLabels(["Name", "Initiative", "HP", "AC"])

        # Filename & Description Fields
        self.filename_input = QLineEdit(self)
        self.filename_input.setPlaceholderText("Enter filename (e.g., goblin_ambush.json)")
        self.description_input = QLineEdit(self)
        self.description_input.setPlaceholderText("Optional: Gist description")

        self.save_button = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.save_button.accepted.connect(self.accept)
        self.save_button.rejected.connect(self.reject)

        # Add widgets to layout
        self.builder_layout.addWidget(QLabel("Filename:"))
        self.builder_layout.addWidget(self.filename_input)
        self.builder_layout.addWidget(QLabel("Gist Description:"))
        self.builder_layout.addWidget(self.description_input)
        self.builder_layout.addWidget(self.encounter_table)
        self.builder_layout.addWidget(self.save_button)

        self.setLayout(self.builder_layout)
        self.resize_table()

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

    def get_metadata(self):
        return {
            "filename": self.filename_input.text().strip(),
            "description": self.description_input.text().strip()
        }

    def resize_table(self):
        self.total_width = self.encounter_table.verticalHeader().width()
        for column in range(self.encounter_table.columnCount()):
            self.encounter_table.resizeColumnToContents(column)
            self.total_width += self.encounter_table.columnWidth(column)
        self.encounter_table.setFixedWidth(
            self.total_width + self.encounter_table.verticalScrollBar().width() + self.encounter_table.frameWidth() * 2
        )


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
        try:
            # List files from Gist
            gists = list_gists()  # This should return a list of gists
            for gist in gists:
                # Extract the file name from the 'files' dictionary
                for file_name in gist['files']:
                    self.file_list.addItem(file_name)  # Add the file name (string) to the list

        except Exception as e:
            print(f"Error while populating file list: {e}")
            # Optionally handle the case where there are no Gists, maybe fallback to local files
            print(f"Directory {self.get_data_path()} not found.")

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

    def populate_file_list(self):
        try:
            # List files from Gist
            gists = list_gists()  # This should return a list of gists
            for gist in gists:
                # Assuming 'gist' contains the file name and Gist ID
                file_name = gist['files'].keys()  # or extract the filename from Gist data
                self.file_list.addItem(file_name)  # Populate the file list with the file names

        except Exception as e:
            print(f"Error while populating file list: {e}")
            # Optionally handle the case where there are no Gists, maybe fallback to local files
            print(f"Directory {self.get_data_path()} not found.")

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
