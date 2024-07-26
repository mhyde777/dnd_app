from typing import List, Dict, Any
import json
import os

from PyQt5.QtWidgets import(
   QDialog, QMessageBox, QTableWidgetItem
) 
from PyQt5.QtGui import QColor

from app.creature import I_Creature, Player, Monster, CustomEncoder
from ui.windows import AddCombatantWindow, RemoveCombatantWindow
from app.save_json import GameState

class Application:

    def __init__(self):
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0

    # JSON Manipulation
    def init_players(self):
        self.load_file_to_manager("players.json")
        
    def load_state(self):
        self.load_file_to_manager("last_state.json")

    def save_state(self):
        file_path = self.get_data_path("last_state.json")
        state = GameState()
        state.players = self.manager.creatures.values()
        state.current_turn = self.current_turn
        state.round_counter = self.round_counter
        state.time_counter = self.time_counter
        save = state.to_dict()
        with open(file_path, 'w') as f:
            json.dump(save, f, cls=CustomEncoder, indent=4)

    def load_file_to_manager(self, file_name):
        file_path = self.get_data_path(file_name)
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                state = json.load(file, object_hook=self.custom_decoder)

            self.manager.creatures.clear()
            players = state.get('players', [])
            monsters = state.get('monsters', [])
            for creature in players + monsters:
                self.manager.add_creature(creature)

            self.current_turn = state['current_turn']
            self.round_counter = state['round_counter']
            self.time_counter = state['time_counter']
            self.current_turn = state['current_turn']
            self.update_table()
            self.update_active_init()
            self.populate_creature_list()
        else:
            return
    
    def custom_decoder(self, data: Dict[str, Any]) -> Any:
        if '_type' in data:
            return I_Creature.from_dict(data)
        return data

    # UI Manipulation
    def update_active_init(self):
        self.sorted_creatures = list(self.manager.creatures.values())
        self.current_creature = self.sorted_creatures[self.current_turn]
        self.current_name = self.current_creature.name
        self.active_init_label.setText(f"Active: {self.current_name}")
        for row in range(self.table.rowCount()):
            if row == self.current_turn:
                color = QColor('#006400')
            else:
                color = QColor('#333')
            self.set_row_color(row, color)

    def set_row_color(self, row, color):
        for column in range(self.table.columnCount()):
            self.table.item(row, column).setBackground(color)
    
    def update_table(self):
        headers = self.get_headers_from_dataclass()
        self.manager.sort_creatures()
        self.table.setRowCount(len(self.manager.creatures))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setColumnHidden(0, True)
        for i, name in enumerate(self.manager.creatures.keys()):
            for j, attr in enumerate(self.manager.creatures[name].__dataclass_fields__):
                self.table.setItem(i, j, QTableWidgetItem(str(getattr(self.manager.creatures[name], attr))))
        self.adjust_table_size()

    def get_headers_from_dataclass(self) -> List[str]:
        field_to_header = {
            '_type': 'CreatureType',
            '_name': 'Name',
            '_init': 'Init',
            '_max_hp': 'Max HP',
            '_curr_hp': 'Curr HP',
            '_armor_class': 'AC',
            '_movement': 'M',
            '_action': 'A',
            '_bonus_action': 'BA',
            '_reaction': 'R',
            '_object_interaction': 'OI',
            '_notes': 'Notes',
            '_status_time': 'Status Time'
        }
        self.fields = [field.name for field in Player.__dataclass_fields__.values() if field.name in field_to_header]
        return [field_to_header[field] for field in self.fields]

    def adjust_table_size(self):
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.resize(self.sizeHint().width() + self.table.sizeHint().width(), self.table.sizeHint().height())

    # Edit Menu Actions
    def load_encounter(self):
        pass

    def add_combatant(self):
        dialog = AddCombatantWindow(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            for creature_data in data:
                creature = Monster(
                    name=creature_data['Name'],
                    init=creature_data['Init'],
                    max_hp=creature_data['HP'],
                    curr_hp=creature_data['HP'],
                    armor_class=creature_data['AC']
                )
                self.manager.add_creature(creature)
            # self.update_table()
            self.update_active_init()
            self.populate_creature_list()

    def remove_combatant(self):
        dialog = RemoveCombatantWindow(self.manager, self)
        if dialog.exec_() == QDialog.Accepted:
            selected_creatures = dialog.get_selected_creatures()
            for name in selected_creatures:
                self.manager.rm_creatures(name)
            self.update_table()
            self.update_active_init()
            self.populate_creature_list()

    # Button Logic
    def next_turn(self):
        self.current_turn += 1
        if self.current_turn >= len(self.manager.creatures):
            self.current_turn = 0
            self.round_counter += 1
            self.time_counter += 6
            self.round_counter_label.setText(f"Round: {self.round_counter}")
            self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        self.update_active_init()

    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.manager.creatures) -1
                self.round_counter -= 1
                self.time_counter -= 6
                self.round_counter_label.setText(f"Round: {self.round_counter}")
                self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        else:
            self.current_turn -= 1
        self.update_active_init()
    
    # def sort_creatures(self):
    #     self.update_table()
    #     self.update_active_init()

    # Path Functions
    def get_image_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'images', filename)

    def get_data_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'data', filename)
    
    def get_parent_dir(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))




    # WIP
    def manipulate_manager(self, item):
        row = item.row()
        col = item.column()
        try:
            creature_name = self.table.item(row, 1).data(0)
        except:
            return
   
        self.column_method_mapping = {
            2: (self.manager.set_creature_init, int),
            3: (self.manager.set_creature_max_hp, int),
            4: (self.manager.set_creature_curr_hp, int),
            5: (self.manager.set_creature_armor_class, int),
            6: (self.manager.set_creature_movement, int),
            7: (self.manager.set_creature_action, bool),
            8: (self.manager.set_creature_bonus_action, bool),
            9: (self.manager.set_creature_reaction, bool),
            10: (self.manager.set_creature_object_interaction, bool),
            11: (self.manager.set_creature_notes, str),
            12: (self.manager.set_creature_status_time, int)
        }

        if creature_name in self.manager.creatures:
            if col in self.column_method_mapping:
                method, data_type = self.column_method_mapping[col]
                try:
                    value = self.get_value(item, data_type)
                    method(creature_name, value)
                except ValueError:
                    return

            self.table.blockSignals(True)
            self.update_table()
            self.table.blockSignals(False)

    def get_value(self, item, data_type):
        text = item.text()
        if data_type == bool:
            return text.lower() in ['true', '1', 'yes']
        return data_type(text)

    def populate_creature_list(self):
        self.creature_list.clear()
        for creature in self.manager.creatures.values():
            self.creature_list.addItem(creature.name)

    def heal_selected_creatures(self):
        self.apply_to_selected_creatures(positive=True)

    def damage_selected_creatures(self):
        self.apply_to_selected_creatures(positive=False)

    def apply_to_selected_creatures(self, positive: bool):
        try:
            value = int(self.value_input.text())
        except ValueError:
            QMessageBox.warning(self, 'Invalid Input', 'Please enter a valid number')
            return

        selected_items = self.creature_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            creature_name = item.text()
            creature = self.manager.creatures[creature_name]
            if creature:
                if positive:
                    creature.curr_hp += value
                else:
                    creature.curr_hp -= value
                    creature.curr_hp = max(0, creature.curr_hp)
        self.populate_creature_list()
