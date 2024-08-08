from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, 
    QPushButton, QToolBar, QWidget, QGridLayout, 
    QHBoxLayout, QGridLayout, QMainWindow, QTableWidget, 
    QTableWidgetItem, QListWidget, QListWidgetItem, QLineEdit,
    QAction, QMenuBar
)
from PyQt5.QtCore import Qt
from app.app import Application
from app.manager import CreatureManager


class InitiativeTracker(QMainWindow, Application): 
    def __init__(self):
        super().__init__()

        self.setWindowTitle("DnD Combat Tracker")
        self.manager = CreatureManager()
        self.initUI()
        self.load_state()

    def initUI(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.mainlayout = QHBoxLayout(self.central_widget)

        self.label_layout = QHBoxLayout()
        
        # Active Init Label 
        self.active_init_label = QLabel(self)
        self.active_init_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.active_init_label, 0)

        # Round counter label 
        self.round_counter_label = QLabel(self)
        self.round_counter_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.round_counter_label, 0)

        # Time counter label 
        self.time_counter_label = QLabel(self)
        self.time_counter_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.time_counter_label, 0)

        # Table Widget
        self.table_layout = QVBoxLayout()
        self.table = QTableWidget(self)
        self.table.setFont(QFont('Arial', 18))
        self.table.itemClicked.connect(self.handle_clicked_item)
        self.table.itemChanged.connect(self.manipulate_manager)
        self.table_layout.addLayout(self.label_layout, 0)
        self.table_layout.addWidget(self.table, 0)
        self.table_layout.addStretch()

        #Buttons
        self.nextprev_layout = QVBoxLayout()

        self.prev_button = QPushButton("Prev", self)
        self.prev_button.clicked.connect(self.prev_turn)
        self.nextprev_layout.addWidget(self.prev_button, 1)
        
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.next_turn)
        self.nextprev_layout.addWidget(self.next_button, 2)

        # Damage/Health Box
        self.dam_layout = QVBoxLayout()

        self.creature_list = QListWidget(self)
        self.creature_list.setSelectionMode(QListWidget.MultiSelection)

        self.value_input = QLineEdit(self)

        self.heal_button = QPushButton("Heal", self)
        self.heal_button.clicked.connect(self.heal_selected_creatures)

        self.dam_button = QPushButton("Damage", self)
        self.dam_button.clicked.connect(self.damage_selected_creatures)

        self.heal_dam_layout = QVBoxLayout()
        self.heal_dam_layout.addWidget(self.heal_button, 1)
        self.heal_dam_layout.addWidget(self.value_input, 2)
        self.heal_dam_layout.addWidget(self.dam_button, 3)
        
        self.creature_list.setFixedWidth(200)
        self.value_input.setFixedWidth(200)
        self.dam_layout.addLayout(self.nextprev_layout, 1)
        self.dam_layout.addWidget(self.creature_list, 2)
        self.dam_layout.addLayout(self.heal_dam_layout, 4)
        self.dam_layout.addStretch()

        # Image Window 
        self.stat_layout = QVBoxLayout()
        self.statblock = QLabel(self)

        self.list_buttons = QHBoxLayout()
        self.monster_list = QListWidget(self)
        self.monster_list.setSelectionMode(QListWidget.SingleSelection)
        self.monster_list.itemSelectionChanged.connect(self.update_statblock_image)
        self.monster_list.setFixedSize(200, 100)

        self.show_hide_butts = QVBoxLayout()
        self.hide_img = QPushButton("Hide Image", self)
        self.hide_img.clicked.connect(self.hide_statblock)

        self.show_img = QPushButton("Show Image", self)
        self.show_img.clicked.connect(self.show_statblock)
        self.show_hide_butts.addWidget(self.show_img, 0)
        self.show_hide_butts.addWidget(self.hide_img, 0)

        self.list_buttons.addWidget(self.monster_list, 0)
        self.list_buttons.addLayout(self.show_hide_butts, 0)
        self.list_buttons.addStretch()

        self.stat_layout.addWidget(self.statblock)
        self.stat_layout.addLayout(self.list_buttons)
        self.stat_layout.addStretch()
       
        # Widgets allow for alignment
        self.dam_widget = QWidget()
        self.dam_widget.setLayout(self.dam_layout)
        
        self.table_widget = QWidget()
        self.table_widget.setLayout(self.table_layout)

        self.stat_widget = QWidget()
        self.stat_widget.setLayout(self.stat_layout)

        self.mainlayout.addWidget(self.dam_widget, alignment=Qt.AlignLeft)
        self.mainlayout.addWidget(self.table_widget, alignment=Qt.AlignLeft)
        self.mainlayout.addStretch()
        self.mainlayout.addWidget(self.stat_widget, alignment=Qt.AlignRight)

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

        self.build_encounter = QAction("Build Encounter", self)
        self.build_encounter.triggered.connect(self.save_encounter)
        self.file_menu.addAction(self.build_encounter)

        self.update_player_file = QAction('Update Player Stats', self)
        self.update_player_file.triggered.connect(self.update_players)
        self.file_menu.addAction(self.update_player_file)

        self.edit_menu.addAction(self.load_enc_button)
        self.edit_menu.addAction(self.add_button)
        self.edit_menu.addAction(self.rmv_button)
