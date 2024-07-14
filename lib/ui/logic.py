from typing import List
from PyQt5.QtGui import QPixmap 
from PyQt5.QtWidgets import *
import pandas as pd

class WidgetLogic:
    def update_active_init(self):
        current_name = self.data.at[self.current_turn, 'Name']
        self.active_init_label.setText(f"Active: {current_name}")

        self.table.selectRow(self.current_turn)


    def next_turn(self):
        self.current_turn += 1
        if self.current_turn >= len(self.data):
            self.current_turn = 0
            self.round_counter += 1
            self.time_counter += 6
            self.round_counter_label.setText(f"Round: {self.round_counter}")
            self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        self.update_active_init()

    def prev_turn(self):
        if self.current_turn == 0:
            if self.round_counter > 1:
                self.current_turn = len(self.data) - 1
                self.round_counter -= 1
                self.time_counter -= 6
                self.round_counter_label.setText(f"Round: {self.round_counter}")
                self.time_counter_label.setText(f"Time: {self.time_counter} seconds")
        else:
            self.current_turn -= 1
        self.update_active_init()

    def load_encounter(self):
        pass

    def add_combat(self):
        dialog = AddCombatants(self)
        if dialog.exec_() == QDialog.Accepted:
            new_data_list = dialog.get_data()
            for new_data in new_data_list:
                self.data = self.data.append(new_data, ignore_index=True)
            self.data = self.data.sort_values(by='Init', ascending=False).reset_index(drop=True)
            self.update_table()

    def rmv_combat(self):
        pass

    def update_table(self):
        self.table.setRowCount(len(self.data))
        for i in range(len(self.data)):
            for j in range(len(self.data.columns)):
                self.table.setItem(i, j, QTableWidgetItem(str(self.data.iat[i,j])))
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
