from PyQt5.QtWidgets import *
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QSize
from app.manager import CreatureManager, Player, Monster

class Application:

    def __init__(self):
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        
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
        dialog = AddCombatant(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            for creature_data in data:
                creature = Player(
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
        dialog = RemoveCombatant(self.manager, self)
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

class AddCombatant(QDialog):
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
        data = []
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

class RemoveCombatant(QDialog):
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
