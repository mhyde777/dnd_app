from typing import List, Dict, Any
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QDialogButtonBox, QListWidget, QListWidgetItem
)


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

