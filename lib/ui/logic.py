from PyQt5.QtWidgets import *


class WidgetLogic:
    def update_active_init(self):
        # current_name = self.data.at[self.current_turn, 'Name']
        # self.active_init_label.setText(f"Active: {current_name}")

        self.table.selectRow(self.current_turn)


    def next_turn(self):
        self.current_turn += 1
        if self.current_turn >= len(self.creatures):
            self.current_turn = 0
            self.round_counter += 1
            self.time_counter += 6
            self.round_counter_label.setText(f"Round: {self.round_counter}")
            self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        self.update_active_init()

    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.creatures) - 1
                self.round_counter -= 1
                self.time_counter -= 6
                self.round_counter_label.setText(f"Round: {self.round_counter}")
                self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        else:
            self.current_turn -= 1
        self.update_active_init()

    def load_encounter(self):
        pass

    def build_encounter(self):
        pass

    # def add_combat(self):
    #     dialog = AddCombatants(self)
    #     if dialog.exec_() == QDialog.Accepted:
    #         new_data_list = dialog.get_data()
    #         for new_data in new_data_list:
    #             self.data = self.data.append(new_data, ignore_index=True)
    #         self.data = self.data.sort_values(by='Init', ascending=False).reset_index(drop=True)
    #         self.update_table()

    def rmv_combat(self):
        pass

    def update_table(self):
        self.table.setRowCount(len(self.creatures))
        for i, name in enumerate(self.manager.creatures.keys()):
            for j, attr in enumerate(self.manager.creatures[name].__dataclass_fields__):
                self.table.setItem(i, j, QTableWidgetItem(str(attr)))
        self.update_active_init()


class AddCombatants(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Combatants")

        self.layout = QVBoxLayout(self)

        self.table = QTableWidget(self)
        self.table.setRowCount(5)  # Allow adding up to 5 creatures at a time
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Name', 'Init', 'HP', 'AC'])

        self.layout.addWidget(self.table)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.layout.addWidget(self.button_box)

    def get_data(self):
        data = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0)
            init = self.table.item(row, 1)
            hp = self.table.item(row, 2)
            ac = self.table.item(row, 3)
            if name and init and hp and ac:
                data.append({
                    'Name': name.text(),
                    'Init': int(init.text()),
                    'HP': int(hp.text()),
                    'AC': int(ac.text())
                })
        return data


class BooleanButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.state = False
        self.update_color()
        self.clicked.connect(self.toggle_state)

    def toggle_state(self):
        self.state = not self.state
        self.update_color()

    def update_color(self):
        if self.state:
            self.setStyleSheet("background-color: green")
        else:
            self.setStyleSheet("background-color: red")
