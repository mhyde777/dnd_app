import os
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QToolBar, QWidget, QGridLayout, QHBoxLayout, QGridLayout, QMainWindow, QTableWidget, QTableWidgetItem

from app.app import *
from app.creature import Player
from app.manager import CreatureManager


class InitiativeTracker(QMainWindow, Application): 
    def __init__(self):
        super().__init__()

        self.setWindowTitle("DnD Combat Tracker")
        # TODO: manager should be wrapped in an application
        #   We can track ui relevant stats on creature number/number attributes
        #   etc... so that constructing ui is easier
        self.manager = CreatureManager()
        chitra = Player(
            name="Chitra",
            init=16,
            max_hp=27,
            curr_hp=27,
            armor_class=16
        )
        echo = Player(
            name="Echo",
            init=20,
            max_hp=21,
            curr_hp=21,
            armor_class=17
        )
        jorji = Player(
            name="Jorji",
            init=8,
            max_hp=21,
            curr_hp=21,
            armor_class=15
        )
        surina = Player(
            name="Surina",
            init=4,
            max_hp=28,
            curr_hp=28,
            armor_class=16
        )
        val = Player(
            name="Val",
            init=12,
            max_hp=25,
            curr_hp=25,
            armor_class=16
        )
        self.manager.add_creature([chitra, echo, jorji, surina, val])
        # 
        # # self.data = pd.DataFrame({
        # #     'Name': ['Chitra', 'Echo', 'Jorji', 'Surina', 'Val'],
        # #     'Init': [16, 20, 8, 4, 12],
        # #     'HP': [27, 21, 21, 28, 25],
        # #     'AC': [16, 17, 15, 16, 16]
        # # }).sort_values(by='Init', ascending=False).reset_index(drop=True)
        #
        # self.current_turn = 0
        # self.round_counter = 1
        # self.time_counter = 0

        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)
        self.initUI()
        # self.update_active_init()


    def initUI(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.mainlayout = QGridLayout(self.central_widget)
        # Table Widget 
        self.table = QTableWidget(self)
        self.mainlayout.addWidget(self.table, 1, 1)
        self.update_table()
        # for i in range(len(self.manager.creatures)):
        #     for j in range(11):
        #         self.table.setItem(i, j, QTableWidgetItem(str(self.data.iat[i,j])))

            # for k, header in enumerate(['A', 'BA', 'R', 'OI']):
            #    button = BooleanButton(header)
            #    self.table.setCellWidget(i, len(self.data.columns) + k, button)

        self.mainlayout.addWidget(self.table, 1 , 1)

        self.label_layout = QHBoxLayout()
        # Active Init Label 
        self.active_init_label = QLabel(self)
        self.active_init_label.setStyleSheet("font-size: 16px;")
        self.label_layout.addWidget(self.active_init_label, 1)

        # Round counter label 
        self.round_counter_label = QLabel(f"Round: {self.round_counter}", self)
        self.round_counter_label.setStyleSheet("font-size: 16px;")
        self.label_layout.addWidget(self.round_counter_label, 2)

        # Time counter label 
        self.time_counter_label = QLabel(f"Time: {self.time_counter} seconds", self)
        self.time_counter_label.setStyleSheet("font-size: 16px;")
        self.label_layout.addWidget(self.time_counter_label, 3)
        
        self.mainlayout.addLayout(self.label_layout, 0, 1)

        #Buttons
        self.nextprev_layout = QVBoxLayout()

        self.prev_button = QPushButton("Prev", self)
        self.prev_button.clicked.connect(self.prev_turn)
        self.nextprev_layout.addWidget(self.prev_button, 1)
        
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.next_turn)
        self.nextprev_layout.addWidget(self.next_button, 2)
        
        self.mainlayout.addLayout(self.nextprev_layout, 1, 0)

        # Load, Add, Remove Buttons
        self.lar_layout = QHBoxLayout()
        
        self.load_enc_button = QPushButton("Load Encounter", self)
        self.load_enc_button.clicked.connect(self.load_encounter)
        self.lar_layout.addWidget(self.load_enc_button, 1)

        self.add_button = QPushButton("Add Combatant", self)
        # self.add_button.clicked.connect(self.add_combat)
        self.lar_layout.addWidget(self.add_button, 2)

        self.rmv_button = QPushButton("Remove Combatants", self)
        # self.rmv_button.clicked.connect(self.rmv_combat)
        self.lar_layout.addWidget(self.rmv_button, 3)

        self.mainlayout.addLayout(self.lar_layout, 2, 1)

        # Image Window 
        self.statblock = QLabel(self)
        self.img = QPixmap(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../images/bean.jpeg')))
        self.statblock.setPixmap(self.img)
        self.mainlayout.addWidget(self.statblock, 1, 2)

        # # Toolbar
        # self.load_encounter_tb = QAction("Load Encounter", self)
        # self.load_encounter_tb.setStatusTip("Encounter")
        # self.load_encounter_tb.triggered.connect(self.load_encounter)
        # self.toolbar.addAction(self.load_encounter_tb)
        #
        # self.build_encounter_tb = QAction("Build Encounter", self)
        # self.build_encounter_tb.setStatusTip("Build")
        # self.build_encounter_tb.trigger.connect(self.build_encounter)
        # self.toolbar.addAction(self.build_encounter_tb)

    def AddCreatureDialog(QDialog):
        pass
