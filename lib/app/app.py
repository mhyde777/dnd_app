from typing import Dict, Any
import json, os, re

from PyQt5.QtWidgets import(
   QDialog, QMessageBox,
    QApplication, QFileDialog, QSizePolicy
) 
from PyQt5.QtGui import (
        QPixmap, QFont
)
from PyQt5.QtCore import (
    Qt, QSize
)
from app.creature import (
    I_Creature, Player, Monster, CustomEncoder, CreatureType
)
from ui.windows import (
    AddCombatantWindow, RemoveCombatantWindow, BuildEncounterWindow, LoadEncounterWindow,
    UpdatePlayerWindow, MergeEncounterWindow
)
from app.save_json import GameState
from app.manager import CreatureManager
from app.gist_utils import load_gist_content, create_or_update_gist

class Application:

    def __init__(self):
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        self.tracking_by_name = False
        self.base_dir = os.path.dirname(__file__)

    # JSON Manipulation
    def init_players(self):
        self.load_file_to_manager("players.json", self.manager)
        # print("Creatures loaded:", list(self.manager.creatures.keys()))
        # print("Sample creature:", next(iter(self.manager.creatures.values())).__dict__)
        # self.table_model.set_fields_from_sample()
        self.statblock.clear()

    def load_state(self):
        self.load_file_to_manager("last_state.json", self.manager)
        self.table_model.set_fields_from_sample()   
    
    def save_state(self):
        self.save_to_json('last_state.json', self.manager)

    def save_as(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(self, "Save File", self.get_data_dir(), "All Files (*);;JSON Files (*.json)", options=options)
        self.save_to_json(file_path, self.manager)

    def save_to_json(self, file, manager):
        file_path = self.get_data_path(file)
        state = GameState()
        state.players = [creature for creature in manager.creatures.values() if isinstance(creature, Player)]
        state.monsters = [creature for creature in manager.creatures.values() if isinstance(creature, Monster)]
        state.current_turn = self.current_turn
        state.round_counter = self.round_counter
        state.time_counter = self.time_counter
        save = state.to_dict()
        with open(file_path, 'w') as f:
            json.dump(save, f, cls=CustomEncoder, indent=4)

    def load_file_to_manager(self, file_name, manager, monsters=False):
        if file_name.startswith("http"):
            # Load from Gist
            state = load_gist_content(file_name)
        else:
            # Load from local file
            file_path = self.get_data_path(file_name)
            if not os.path.exists(file_path):
                return
            with open(file_path, 'r') as file:
                state = json.load(file, object_hook=self.custom_decoder)

        if monsters:
            monsters = state.get('monsters', [])
            for creature in monsters:
                manager.add_creature(creature)
        else:
            manager.creatures.clear()
            players = state.get('players', [])
            monsters = state.get('monsters', [])
            for creature in players + monsters:
                manager.add_creature(creature)

            self.current_turn = state['current_turn']
            self.round_counter = state['round_counter']
            self.time_counter = state['time_counter']

        self.sorted_creatures = list(manager.creatures.values())
        self.current_creature_name = self.sorted_creatures[0].name if self.sorted_creatures else None

        if self.sorted_creatures and self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
            self.active_statblock_image(self.sorted_creatures[self.current_turn])

        self.table_model.set_fields_from_sample()
        self.table_model.refresh()  # <-- Add this!
        self.update_table()

    def custom_decoder(self, data: Dict[str, Any]) -> Any:
        if '_type' in data:
            return I_Creature.from_dict(data)
        return data

    # UI Manipulation
    def update_table(self):
        self.manager.sort_creatures()
        self.table_model.refresh()
        self.pop_lists()
        self.update_active_init()

        if '_type' in self.table_model.fields:
            type_index = self.table_model.fields.index('_type')
            self.table.setColumnHidden(type_index, True)
            print(f"✅ Column '_type' at index {type_index} was hidden.")

        self.adjust_table_size()

        # Hide Creature Type column if present
        if '_type' in self.table_model.fields:
            type_index = self.table_model.fields.index('_type')
            self.table.setColumnHidden(type_index, True)

        self.table.setColumnHidden(type_index, True)

    def update_active_init(self):
        self.sorted_creatures = list(self.manager.creatures.values())
        if not self.sorted_creatures:
            self.active_init_label.setText("Active: None")
            return

        if self.tracking_by_name:
            if not self.current_creature_name:
                self.current_creature_name = self.sorted_creatures[0].name
            self.current_turn = next(
                (i for i, creature in enumerate(self.sorted_creatures) if creature.name == self.current_creature_name),
                0
            )

        self.current_creature = self.sorted_creatures[self.current_turn]
        self.current_name = self.current_creature.name

        self.active_init_label.setText(f"Active: {self.current_name}")
        self.round_counter_label.setText(f"Round: {self.round_counter}")
        self.time_counter_label.setText(f"Time: {self.time_counter} seconds")

        # Let the model know which creature is active
        if hasattr(self.table_model, "set_active_creature"):
            self.table_model.set_active_creature(self.current_name)

    def set_row_color(self, row, color):
        for column in range(self.table.columnCount()):
            item = None
            if item:
                item.setBackground(color)
    
    def init_tracking_mode(self, by_name):
        self.tracking_by_name = by_name

    def adjust_table_size(self):
        screen_geometry = QApplication.desktop().availableGeometry(self)
        screen_height = screen_geometry.height()

        font_size = max(int(screen_height * 0.012), 10) if screen_height < 1440 else 18
        self.table.setFont(QFont('Arial', font_size))

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

        total_width = self.table.verticalHeader().width()
        for col in range(self.table.model().columnCount()):
            if not self.table.isColumnHidden(col):
                total_width += self.table.columnWidth(col)

        total_height = self.table.horizontalHeader().height()
        for row in range(self.table.model().rowCount()):
            total_height += self.table.rowHeight(row)

        # Remove scrollbars, set exact size
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setFixedSize(total_width + 2, total_height + 2)

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
        if self.current_turn >= len(self.sorted_creatures):
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

        self.current_creature_name = self.sorted_creatures[self.current_turn].name
        self.manager.creatures[self.current_creature_name].reaction = False

        self.update_active_init()

        if self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
            self.active_statblock_image(self.sorted_creatures[self.current_turn])
    
    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.manager.creatures) - 1
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

    def get_data_dir(self):
        return os.path.join(self.get_parent_dir(), 'data')
    
    def get_parent_dir(self):
        return os.path.abspath(os.path.join(self.base_dir, '../../'))

    def get_extensions(self):
        return ('png', 'jpg', 'jpeg', 'gif')

    # Change Manager with Changes to Table
    def manipulate_manager(self, item):
        row = item.row()
        col = item.column()
        try:
            creature_name = None.data(0)
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
        if selected_items:
            monster_name = selected_items[0].text()
            self.resize_to_fit_screen(monster_name)
        else:
            self.statblock.clear()

    def active_statblock_image(self, creature_name):
        base_name = self.get_base_name(creature_name)
        self.resize_to_fit_screen(base_name)

    def resize_to_fit_screen(self, base_name):
        # self.statblock.clear()
        screen_geometry = QApplication.desktop().availableGeometry(self)
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()
        extensions = self.get_extensions() 
        for ext in extensions:
            image_path = self.get_image_path(f'{base_name}.{ext}')
            if os.path.exists(image_path):
                self.pixmap = QPixmap(image_path)
                h_shift = screen_width / 2440 if screen_width < 2560 else 1
                v_shift = screen_height / 1440 if screen_height < 1440 else 1
                new_size = QSize(int(self.pixmap.width() * h_shift), int(self.pixmap.height() * v_shift))
                scaled_pixmap = self.pixmap.scaled(new_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.statblock.setPixmap(scaled_pixmap)

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
            state.players = [c for c in encounter_manager.creatures.values() if isinstance(c, Player)]
            state.monsters = [c for c in encounter_manager.creatures.values() if isinstance(c, Monster)]
            state.current_turn = 0
            state.round_counter = 1
            state.time_counter = 0
            save = state.to_dict()

            filename = dialog.filename_input.text().strip().replace(' ', '_') + '.json'

            try:
                gist_response = create_or_update_gist(filename, save)
                gist_url = gist_response['html_url']
                raw_url = list(gist_response['files'].values())[0]['raw_url']
                QMessageBox.information(self, "Saved to Gist", f"Gist created:\n{gist_url}\n\nRaw URL:\n{raw_url}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save gist:\n{e}")
    

    # def save_encounter(self):
    #     dialog = BuildEncounterWindow(self)
    #     if dialog.exec_() == QDialog.Accepted:
    #         data = dialog.get_data()
    #         encounter_manager = CreatureManager()
    #         self.load_file_to_manager('players.json', encounter_manager)
    #         for creature_data in data:
    #             creature = Monster(
    #                 name=creature_data['Name'],
    #                 init=creature_data['Init'],
    #                 max_hp=creature_data['HP'],
    #                 curr_hp=creature_data['HP'],
    #                 armor_class=creature_data['AC']
    #             )
    #             encounter_manager.add_creature(creature)
    #         state = GameState()
    #         state.players = [creature for creature in encounter_manager.creatures.values() if isinstance(creature, Player)]
    #         state.monsters = [creature for creature in encounter_manager.creatures.values() if isinstance(creature, Monster)]
    #         state.current_turn = 0
    #         state.round_counter = 1
    #         state.time_counter = 0
    #         save = state.to_dict()
    #         filename = dialog.filename_input.text().strip()
    #         filename = filename.replace(' ', '_')
    #         file_path = self.get_data_path(f"{filename}.json")
    #         with open(file_path, 'w') as f:
    #             json.dump(save, f, cls=CustomEncoder, indent=4)

    def load_encounter(self):
        dialog = LoadEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted:
            # Use Google Drive
            self.load_file_to_manager(f'{dialog.selected_file}.json', self.manager)

            if self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
                self.active_statblock_image(self.sorted_creatures[self.current_turn])

    # def load_encounter(self):
    #     dialog = LoadEncounterWindow(self)
    #     if dialog.exec_() == QDialog.Accepted:
    #         self.load_file_to_manager(f'{dialog.selected_file}.json', self.manager)
    #         if self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
    #             self.active_statblock_image(self.sorted_creatures[self.current_turn])

    def merge_encounter(self):
        dialog = MergeEncounterWindow(self)
        if dialog.exec_() == QDialog.Accepted:
            self.load_file_to_manager(f'{dialog.selected_file}.json', self.manager, monsters=True)
            if self.sorted_creatures[self.current_turn]._type == CreatureType.MONSTER:
                self.active_statblock_image(self.sorted_creatures[self.current_turn])
    # WIP
    def update_players(self):
        dialog = UpdatePlayerWindow(self)
        headers = ['Name', 'Max HP', 'AC']
        self.player_manager = CreatureManager()
        self.load_file_to_manager('players.json', self.player_manager)
        dialog.player_table.setRowCount(len(self.player_manager.creatures.keys()))
        dialog.player_table.setColumnCount(len(headers))
        dialog.player_table.setHorizontalHeaderLabels(headers)
        
        dialog.resize_table()
        if dialog.exec_() == QDialog.Accepted:
            pass
