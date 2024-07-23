import os
from PyQt5.QtGui import QPixmap, QFont
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
        # chitra = Player(
        #     name="Chitra",
        #     init=16,
        #     max_hp=27,
        #     curr_hp=27,
        #     armor_class=16
        # )
        # echo = Player(
        #     name="Echo",
        #     init=20,
        #     max_hp=21,
        #     curr_hp=21,
        #     armor_class=17
        # )
        # jorji = Player(
        #     name="Jorji",
        #     init=8,
        #     max_hp=21,
        #     curr_hp=21,
        #     armor_class=15
        # )
        # surina = Player(
        #     name="Surina",
        #     init=4,
        #     max_hp=28,
        #     curr_hp=28,
        #     armor_class=16
        # )
        # val = Player(
        #     name="Val",
        #     init=12,
        #     max_hp=25,
        #     curr_hp=25,
        #     armor_class=16
        # )
        # self.manager.add_creature([chitra, echo, jorji, surina, val])
        self.initUI()
        self.load_state()

    def initUI(self):
        width = 1115
        height = 300
        self.setMinimumSize(width, height)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.mainlayout = QGridLayout(self.central_widget)
        # Table Widget
        self.table_layout = QHBoxLayout()
        self.table = QTableWidget(self)
        self.table.setFont(QFont('Arial', 18))
        self.table_layout.addWidget(self.table)
        self.update_table()

        self.label_layout = QHBoxLayout()
        # Active Init Label 
        self.active_init_label = QLabel(self)
        self.active_init_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.active_init_label, 1)

        # Round counter label 
        self.round_counter_label = QLabel(f"Round: {self.round_counter}", self)
        self.round_counter_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.round_counter_label, 2)

        # Time counter label 
        self.time_counter_label = QLabel(f"Time: {self.time_counter} seconds", self)
        self.time_counter_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.time_counter_label, 3)

        #Buttons
        self.nextprev_layout = QVBoxLayout()

        self.prev_button = QPushButton("Prev", self)
        self.prev_button.clicked.connect(self.prev_turn)
        self.nextprev_layout.addWidget(self.prev_button, 1)
        
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.next_turn)
        self.nextprev_layout.addWidget(self.next_button, 2)

        # Load, Add, Remove Buttons
        # self.lar_layout = QHBoxLayout()
        # 
        # self.load_enc_button = QPushButton("Load Encounter", self)
        # self.load_enc_button.clicked.connect(self.load_encounter)
        # self.lar_layout.addWidget(self.load_enc_button, 1)
        #
        # self.add_button = QPushButton("Add Combatant", self)
        # self.add_button.clicked.connect(self.add_combatant)
        # self.lar_layout.addWidget(self.add_button, 2)
        #
        # self.rmv_button = QPushButton("Remove Combatants", self)
        # self.rmv_button.clicked.connect(self.remove_combatant)
        # self.lar_layout.addWidget(self.rmv_button, 3)

        # Image Window 
        self.stat_layout = QHBoxLayout()
        self.statblock = QLabel(self)
        self.img = QPixmap(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../images/bean.jpeg')))
        self.statblock.setPixmap(self.img)
        self.stat_layout.addWidget(self.statblock)

        self.mainlayout.addLayout(self.table_layout, 1, 1)
        self.mainlayout.addLayout(self.label_layout, 0, 1)
        self.mainlayout.addLayout(self.nextprev_layout, 2, 0)
        # self.mainlayout.addLayout(self.lar_layout, 2, 1)
        self.mainlayout.addLayout(self.stat_layout, 1, 2)
        self.adjust_table_size()

        # Menu Bar
        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)

        self.file_menu = self.menu_bar.addMenu("&File")
        self.edit_menu = self.menu_bar.addMenu("&Edit")
        
        # Toolbar
        self.filetool_bar = QToolBar("File", self)
        self.addToolBar(self.filetool_bar)

        # Actions
        self.save_action = QAction("Save", self)
        self.save_action.triggered.connect(self.save_state)
        self.file_menu.addAction(self.save_action)

        self.initialize_players_action = QAction("Initialize", self)
        self.initialize_players_action.triggered.connect(self.init_players)
        self.file_menu.addAction(self.initialize_players_action)


        self.load_enc_button = QAction("Load Encounter", self)
        self.load_enc_button.triggered.connect(self.load_encounter)
        self.filetool_bar.addAction(self.load_enc_button)

        self.add_button = QAction("Add Combatant", self)
        self.add_button.triggered.connect(self.add_combatant)
        self.filetool_bar.addAction(self.add_button)

        self.rmv_button = QAction("Remove Combatants", self)
        self.rmv_button.triggered.connect(self.remove_combatant)
        self.filetool_bar.addAction(self.rmv_button)
                       
        self.file_menu.addAction(self.load_enc_button)
        self.file_menu.addAction(self.add_button)
        self.file_menu.addAction(self.rmv_button)
        
