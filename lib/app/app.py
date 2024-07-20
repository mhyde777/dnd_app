from PyQt5.QtWidgets import QDialogButtonBox, QPushButton, QTableWidget, QTableWidgetItem
# from app.manager import CreatureManager

class Application:

    def __init__(self):
        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0
        
        # self.update_active_init()
    #
    # def update_active_init(self):
    #     self.current_name = self.manager.creatures.keys()
    #     self.active_init_label.setText(f"Active: {self.current_name}")
    #     self.table.selectRow(self.current_turn)

    def load_encounter(self):
        pass

    def add_combatant(self):
        pass

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
        # self.update_active_init()

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
        # self.update_active_init()

    def update_table(self):
        headers = ['CreatureType', 'Name', 'Init', 'Max HP', 'Curr HP', 'Armor Class', 'M', 'A', 'BA', 'R', 'OI', 'Notes', 'Status Time']

        self.table.setRowCount(len(self.manager.creatures))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setColumnHidden(0, True)
        self.table.resizeColumnsToContents()
        for i, name in enumerate(self.manager.creatures.keys()):
            for j, attr in enumerate(self.manager.creatures[name].__dataclass_fields__):
                self.table.setItem(i, j, QTableWidgetItem(str(getattr(self.manager.creatures[name], attr))))
