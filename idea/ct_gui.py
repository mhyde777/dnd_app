from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
import pandas as pd 
import sys

class InitiativeTracker(QMainWindow): 
    def __init__(self):
        super().__init__()

        self.setWindowTitle("DnD Combat Tracker")
        
        self.data = pd.DataFrame({
            'Name': ['Chitra', 'Echo', 'Jorji', 'Surina', 'Val'],
            'Init': [16, 20, 8, 4, 12],
            'HP': [27, 21, 21, 28, 25],
            'AC': [16, 17, 15, 16, 16]
        }).sort_values(by='Init', ascending=False).reset_index(drop=True)

        self.current_turn = 0
        self.round_counter = 1
        self.time_counter = 0

        self.initUI()
        self.update_active_init()


    def initUI(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.mainlayout = QGridLayout(self.central_widget)
        
        # Table Widget 
        self.table = QTableWidget(self)
        self.table.setRowCount(len(self.data))
        self.table.setColumnCount(len(self.data.columns))
        self.table.setHorizontalHeaderLabels(self.data.columns)


        for i in range(len(self.data)):
            for j in range(len(self.data.columns)):
                self.table.setItem(i, j, QTableWidgetItem(str(self.data.iat[i,j])))

        self.mainlayout.addWidget(self.table, 0 , 1)

        self.label_layout = QVBoxLayout()
        # Active Init Label 
        self.active_init_label = QLabel(self)
        self.active_init_label.setStyleSheet("font-size: 16px;")
        self.label_layout.addWidget(self.active_init_label)

        # Round counter label 
        self.round_counter_label = QLabel(f"Round: {self.round_counter}", self)
        self.round_counter_label.setStyleSheet("font-size: 16px;")
        self.label_layout.addWidget(self.round_counter_label)

        # Time counter label 
        self.time_counter_label = QLabel(f"Time: {self.time_counter} seconds", self)
        self.time_counter_label.setStyleSheet("font-size: 16px;")
        self.label_layout.addWidget(self.time_counter_label)
        
        self.mainlayout.addLayout(self.label_layout, 0, 2)

        #Buttons
        self.buttons_layout = QVBoxLayout()

        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.next_turn)
        self.buttons_layout.addWidget(self.next_button)

        self.prev_button = QPushButton("Prev", self)
        self.prev_button.clicked.connect(self.prev_turn)
        self.buttons_layout.addWidget(self.prev_button)

        self.mainlayout.addLayout(self.buttons_layout, 0, 0)

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = InitiativeTracker()
    window.show()
    app.exec_()
