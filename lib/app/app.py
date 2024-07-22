from typing import List, Dict, Any
import json
import os

from PyQt5.QtWidgets import *
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QSize

from app.manager import CreatureManager
from app.creature import Player, Monster
from ui.windows import AddCombatantWindow, RemoveCombatantWindow


class Application:

    def __init__(self):
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        

    def init_players(self):
        try:
            file_path = self.get_data_path('players.json')
            
            print(f"Attemtping to load player data from {file_path}")

            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    players = json.load(file)
                    print(f"Player data loaded: {players}")

                for name, data in players.items():
                    player = Player(**data)
                    self.manager.add_creature(player)
                    print(f"Added player: {name}")

                self.update_table()
                self.update_active_init()
            else:
                return
        except Exception as e:
            print(f"Error: {e}")

    def save_state(self):
        file_path = self.get_data_path("last_state.json")
        state = {
            'creatures': {name: creature.__dict__ for name, creature in self.manager.creatures.items()},
            'current_turn': self.current_turn,
            'round_counter': self.round_counter,
            'time_counter': self.time_counter
        }
        
        with open(file_path, 'w') as file:
            json.dump(state, file, indent=4)

    def load_state(self):
        file_path = self.get_data_path("last_state.json")
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                state = json.load(file)

            self.manager.creatures.clear()
            player_names = ["Chitra", "Echo", "Jorji", "Surina", "Val"]
            # I know this isn't how I want to do this
            for name, data in state['creatures'].items():
                if name in player_names:
                    creature = Player(**data)
                else:
                    creature = Monster(**data)
                self.manager.creatures[name] = creature
            self.current_turn = state['current_turn']
            self.round_counter = state['round_counter']
            self.time_counter = state['time_counter']
            self.update_table()
            self.update_active_init()
        else:
            return

    def update_active_init(self):
        self.sorted_creatures = list(self.manager.creatures.values())
        self.current_creature = self.sorted_creatures[self.current_turn]
        self.current_name = self.current_creature.name
        self.active_init_label.setText(f"Active: {self.current_name}")
        for row in range(self.table.rowCount()):
            color = QColor(255, 255, 255)
            if row == self.current_turn:
                color = QColor(160, 255, 150)
            self.set_row_color(row, color)

    def set_row_color(self, row, color):
        for column in range(self.table.columnCount()):
            self.table.item(row, column).setBackground(color)

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
            self.update_table()
            self.update_active_init()

    def remove_combatant(self):
        dialog = RemoveCombatantWindow(self.manager, self)
        if dialog.exec_() == QDialog.Accepted:
            selected_creatures = dialog.get_selected_creatures()
            for name in selected_creatures:
                self.manager.rm_creatures(name)
            self.update_table()
            self.update_active_init()

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

    def update_table(self):
        # TODO: Find out how to read from dataclass fields - omit some - rename others
        headers = ['CreatureType', 'Name', 'Init', 'Max HP', 'Curr HP', 'Armor Class', 'M', 'A', 'BA', 'R', 'OI', 'Notes', 'Status Time']
        self.manager.sort_creatures()
        self.table.setRowCount(len(self.manager.creatures))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setColumnHidden(0, True)
        for i, name in enumerate(self.manager.creatures.keys()):
            for j, attr in enumerate(self.manager.creatures[name].__dataclass_fields__):
                self.table.setItem(i, j, QTableWidgetItem(str(getattr(self.manager.creatures[name], attr))))
        self.adjust_table_size()

    def adjust_table_size(self):
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.resize(self.sizeHint().width() + self.table.sizeHint().width(), self.table.sizeHint().height())

    def get_data_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'data', filename)
    
    def get_parent_dir(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))

