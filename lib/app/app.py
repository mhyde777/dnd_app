from typing import List, Dict, Any
import json, os, re

from PyQt5.QtWidgets import(
   QDialog, QMessageBox, QTableWidgetItem
) 
from PyQt5.QtGui import (
        QColor, QPixmap
)
from PyQt5.QtCore import (
    Qt
)
from app.creature import (
    I_Creature, Player, Monster, CustomEncoder, CreatureType
)
from ui.windows import (
    AddCombatantWindow, RemoveCombatantWindow, BuildEncounterWindow, LoadEncounterWindow,
    UpdatePlayerWindow
)
from app.save_json import GameState
from app.manager import CreatureManager

class Application:

    def __init__(self):
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        self.tracking_by_name = False
        self.boolean_columns = {7, 8, 9, 10}
        self.base_dir = os.path.dirname(__file__)

    # JSON Manipulation
    def init_players(self):
        self.load_file_to_manager("players.json", self.manager)
        self.statblock.clear()

    def load_state(self):
            self.load_file_to_manager("last_state.json", self.manager)

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

    def load_file_to_manager(self, file_name, manager):
        file_path = self.get_data_path(file_name)
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                state = json.load(file, object_hook=self.custom_decoder)

            manager.creatures.clear()
            players = state.get('players', [])
            monsters = state.get('monsters', [])
            for creature in players + monsters:
                manager.add_creature(creature)

            self.current_turn = state['current_turn']
            self.round_counter = state['round_counter']
            self.time_counter = state['time_counter']
            self.sorted_creatures = list(manager.creatures.values())
            if self.sorted_creatures:
                self.current_creature_name = self.sorted_creatures[0].name
            else:
                self.current_creature_name = None
            self.update_table()
        else:
            return
    
    def custom_decoder(self, data: Dict[str, Any]) -> Any:
        if '_type' in data:
            return I_Creature.from_dict(data)
        return data

    # UI Manipulation
    def update_table(self):
        headers = self.get_headers_from_dataclass()
        self.manager.sort_creatures()
        self.table.setRowCount(len(self.manager.creatures))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setColumnHidden(0, True)
        self.table.setWordWrap(True)
        for i, name in enumerate(self.manager.creatures.keys()):
            for j, attr in enumerate(self.manager.creatures[name].__dataclass_fields__):
                value = getattr(self.manager.creatures[name], attr, None)
                item = QTableWidgetItem(str(value))
                if j in self.boolean_columns:
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if value else Qt.Unchecked)
                self.table.setItem(i, j, item)
        self.pop_lists()
        self.update_active_init()
        self.adjust_table_size()

    def update_active_init(self):
        self.sorted_creatures = list(self.manager.creatures.values())
        if not self.sorted_creatures:
            self.active_init_label.setText("Active: None")
            return

        if self.tracking_by_name:
            if not self.current_creature_name:
                self.current_creature_name = self.sorted_creatures[0].name

            self.current_turn = next((i for i, creature in enumerate(self.sorted_creatures) if creature.name == self.current_creature_name), 0)

        self.current_creature = self.sorted_creatures[self.current_turn]
        self.current_name = self.current_creature.name
        self.active_init_label.setText(f"Active: {self.current_name}")
        self.round_counter_label.setText(f'Round: {self.round_counter}')
        self.time_counter_label.setText(f'Time: {self.time_counter} seconds')

        self.boolean_attributes = {
            7: 'action',
            8: 'bonus_action',
            9: 'reaction',
            10: 'object_interaction'
        }

        for row in range(self.table.rowCount()):
            color = QColor('#333')
            creature_name = self.table.item(row, 1).text()
            creature = self.manager.creatures.get(creature_name)

            if row == self.current_turn and creature.curr_hp != 0:
                color = QColor('#006400')
            elif row == self.current_turn and creature.curr_hp == 0:
                color = QColor('red')
            else:
                if creature and creature.curr_hp == 0:
                    color = QColor('darkRed')
            self.set_row_color(row, color)
            
            for col in self.boolean_columns:
                item = self.table.item(row, col)
                if item:
                    creature_name = self.table.item(row, 1).text()
                    creature = self.manager.creatures.get(creature_name)
                    if creature:
                        attribute_name = self.boolean_attributes.get(col)
                        value = getattr(creature, attribute_name, False) if attribute_name else False
                        item.setBackground(QColor('red') if not value else QColor('#006400'))
                        item.setForeground(QColor('red') if not value else QColor('#006400'))


    def set_row_color(self, row, color):
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                item.setBackground(color)
    
    def init_tracking_mode(self, by_name):
        self.tracking_by_name = by_name
    
    def toggle_bool_value(self, row, col):
        if col not in self.boolean_columns:
                    return

        item = self.table.item(row, col)
        if item:
            current_text = item.text()
            new_text = "True" if current_text == "False" else "False"
            item.setText(new_text)
            creature_name = self.table.item(row, 1).text()
            if creature_name in self.manager.creatures:
                # TODO: How the fuck do I do this without mapping?
                method_mapping = {
                    7: self.manager.set_creature_action,
                    8: self.manager.set_creature_bonus_action,
                    9: self.manager.set_creature_reaction,
                    10: self.manager.set_creature_object_interaction
                }
                if col in method_mapping:
                    method = method_mapping[col]
                    method(creature_name, new_text == 'True')
        self.update_active_init()

    def handle_clicked_item(self, item: QTableWidgetItem):
        row = item.row()
        col = item.column()
        self.toggle_bool_value(row, col)

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
        total_width = self.table.verticalHeader().width()
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)
            total_width += self.table.columnWidth(column)

        total_height = self.table.horizontalHeader().height()
        for row in range(self.table.rowCount()):
            self.table.resizeRowToContents(row)
            total_height += self.table.rowHeight(row)

        self.table.setFixedWidth(total_width + self.table.frameWidth() * 2)
        self.table.setFixedHeight(total_height + self.table.frameWidth() * 2)

    def pop_lists(self):
        self.populate_monster_list()
        self.populate_creature_list()

    def populate_creature_list(self):
        self.creature_list.clear()
        for creature in self.manager.creatures.values():
            self.creature_list.addItem(creature.name)

        list_height = self.creature_list.count() * self.creature_list.sizeHintForRow(0)
        list_height += self.creature_list.frameWidth()*2
        self.creature_list.setFixedHeight(list_height)
        

    def populate_monster_list(self):
        self.monster_list.clear()
        unique_monster_names = set()

        for creature in self.manager.creatures.values():
            if creature._type == CreatureType.MONSTER:
                base_name = self.get_base_name(creature)
                unique_monster_names.add(base_name)

        for name in unique_monster_names:
            self.monster_list.addItem(name)

        list_height = self.monster_list.count() * self.monster_list.sizeHintForRow(0)
        list_height += self.monster_list.frameWidth()*2
        self.monster_list.setFixedHeight(list_height)

        if self.monster_list.count() == 0:
            self.hide_img.hide()
            self.show_img.hide()
            self.monster_list.hide()
        else:
            self.hide_img.show()
            self.show_img.show()
            self.monster_list.show()

    def get_base_name(self, creature):
        non_num_name = re.sub(r'\d+$', '', creature.name)
        base_name = non_num_name.strip()
        return base_name

    # Edit Menu Actions
    def add_combatant(self):
        self.init_tracking_mode(True)
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
            self.pop_lists()
            self.update_table()
        self.init_tracking_mode(False)

    def remove_combatant(self):
        self.init_tracking_mode(True)
        dialog = RemoveCombatantWindow(self.manager, self)
        if dialog.exec_() == QDialog.Accepted:
            selected_creatures = dialog.get_selected_creatures()
            for name in selected_creatures:
                self.manager.rm_creatures(name)
            self.update_table()
            self.pop_lists()
            if self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
                self.active_statblock_image(self.sorted_creatures[self.current_turn])
            else:
                self.statblock.clear()
        self.init_tracking_mode(False)

    # Button Logic
    def next_turn(self):
        self.current_turn += 1
        if self.current_turn >= len(self.manager.creatures):
            self.current_turn = 0
            self.round_counter += 1
            self.time_counter += 6
            self.round_counter_label.setText(f"Round: {self.round_counter}")
            self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
            for creature in self.manager.creatures.values():
                if creature.status_time:
                    creature.status_time -= 6
                creature.action = False
                creature.bonus_action = False
                creature.object_interaction = False
            self.update_table()

        self.current_creature_name = self.sorted_creatures[self.current_turn].name
        self.manager.creatures[self.current_creature_name].reaction = False
        for col in self.boolean_columns:
            attribute_name = self.boolean_attributes.get(col)
            if attribute_name:
                value = getattr(self.manager.creatures[self.current_creature_name], attribute_name, False)
                item = self.table.item(self.current_turn, col)
                if item:
                    item.setText('True' if value else 'False')
        self.update_active_init()

        if self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
            self.active_statblock_image(self.sorted_creatures[self.current_turn])

    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.manager.creatures) -1
                self.round_counter -= 1
                self.time_counter -= 6
                self.round_counter_label.setText(f"Round: {self.round_counter}")
                self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
                for creature in self.manager.creatures.values():
                    if creature.status_time:
                        creature.status_time += 6
        else:
            self.current_turn -= 1
        
        self.current_creature_name = self.sorted_creatures[self.current_turn].name
        self.update_active_init()

        if self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
            self.active_statblock_image(self.sorted_creatures[self.current_turn])

    # Path Functions
    def get_image_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'images', filename)

    def get_data_path(self, filename):
        return os.path.join(self.get_parent_dir(), 'data', filename)
    
    def get_parent_dir(self):
        return os.path.abspath(os.path.join(self.base_dir, '../../'))

    def get_extensions(self):
        return ('png', 'jpg', 'jpeg', 'gif')

    # Change Manager with Changes to Table
    def manipulate_manager(self, item):
        row = item.row()
        col = item.column()
        try:
            creature_name = self.table.item(row, 1).data(0)
        except:
            return
        # TODO: How do I do this without mapping?
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
                    if col == 12 and (item.text().strip() == "" or item.text() is None):
                        value = ""
                    else:
                        value = self.get_value(item, data_type)
                    method(creature_name, value)
                except ValueError:
                    return
        self.adjust_table_size()
        self.table.blockSignals(True)
        self.update_table()
        self.table.blockSignals(False)

    def get_value(self, item, data_type):
        text = item.text()
        if data_type == bool:
            return text.lower() in ['true', '1', 'yes']
        return data_type(text)
    
    # Image Label
    def update_statblock_image(self):
        selected_items = self.monster_list.selectedItems()
        extensions = self.get_extensions()
        if selected_items:
            monster_name = selected_items[0].text()
            for ext in extensions:
                image_path = self.get_image_path(f'{monster_name}.{ext}')
                if os.path.exists(image_path):
                    pixmap = QPixmap(image_path)
                    self.statblock.setPixmap(pixmap)
                    self.statblock.resize(pixmap.size())
                    return

            self.statblock.clear()
        else:
            self.statblock.clear()

    def active_statblock_image(self, creature_name):
        base_name = self.get_base_name(creature_name)
        extensions = self.get_extensions()
        for ext in extensions:
            image_path = self.get_image_path(f'{base_name}.{ext}')
            if os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                self.statblock.setPixmap(pixmap)
                self.statblock.resize(pixmap.size())
                return

    def hide_statblock(self):
        self.statblock.hide()

    def show_statblock(self):
        self.statblock.show()

    # Damage/Healing 
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
        self.value_input.clear()
        self.pop_lists()
        self.update_table()

    # Encounter Builder
    def save_encounter(self):
        dialog = BuildEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            encounter_manager = CreatureManager()
            self.load_file_to_manager('players.json', encounter_manager)
            for creature_data in data:
                creature = Monster(
                    name=creature_data['Name'],
                    init=creature_data['Init'],
                    max_hp=creature_data['HP'],
                    curr_hp=creature_data['HP'],
                    armor_class=creature_data['AC']
                )
                encounter_manager.add_creature(creature)
            state = GameState()
            state.players = encounter_manager.creatures.values()
            state.current_turn = 0
            state.round_counter = 1
            state.time_counter = 0
            save = state.to_dict()
            filename = dialog.filename_input.text().strip()
            filename = filename.replace(' ', '_')
            file_path = self.get_data_path(f"{filename}.json")
            with open(file_path, 'w') as f:
                json.dump(save, f, cls=CustomEncoder, indent=4)

    def load_encounter(self):
        dialog = LoadEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted:
            self.load_file_to_manager(f'{dialog.selected_file}.json', self.manager)

    def update_players(self):
        dialog = UpdatePlayerWindow(self)
        headers = ['Name', 'Max HP', 'AC']
        dialog.player_table.setHorizontalHeaderLabels(headers)
        if dialog.exec_() == QDialog.Accepted:
            pass
