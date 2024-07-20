from PyQt5.QtWidgets import *
from PyQt5.QtGui import QColor
from app.manager import CreatureManager, Player, Monster

class Application:

    def __init__(self):
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        
        # self.update_active_init()
    #
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
        pass

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
        self.table.resizeColumnsToContents()
        for i, name in enumerate(self.manager.creatures.keys()):
            for j, attr in enumerate(self.manager.creatures[name].__dataclass_fields__):
                self.table.setItem(i, j, QTableWidgetItem(str(getattr(self.manager.creatures[name], attr))))

class AddCombatant(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Combatants")

        self.layout = QVBoxLayout()

        self.add_table = QTableWidget(self)
        self.add_table.setRowCount(5)
        self.add_table.setColumnCount(4)
        self.add_table.setHorizontalHeaderLabels(['Name', 'Init', 'HP', 'AC'])

        self.layout.addWidget(self.add_table, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.layout.addWidget(self.button_box, 2)
        self.setLayout(self.layout)


    def get_data(self):
        data = []
        for row in range(self.add_table.rowCount()):
            name = self.add_table.item(row, 0)
            init = self.add_table.item(row, 1)
            hp = self.add_table.item(row, 2)
            ac = self.add_table.item(row, 3)
            if name and init and hp and ac:
                data.appen({
                    'Name': name.text(),
                    'Init': int(init.text()),
                    'HP': int(hp.text()),
                    'AC': int(ac.text())
                })
        return data
