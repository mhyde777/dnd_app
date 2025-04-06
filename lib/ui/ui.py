from PyQt5.QtWidgets import (
    QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QToolBar, QWidget,
    QHBoxLayout, QMainWindow, QListWidget,
    QAction, QMenuBar, QDesktopWidget, QTableView
)
from PyQt5.QtCore import Qt
from app.app import Application
from app.manager import CreatureManager
from ui.creature_table_model import CreatureTableModel


class InitiativeTracker(QMainWindow, Application): 
    def __init__(self):
        super().__init__()
        self.center()
        self.update_size_constraints()
        self.setWindowTitle("DnD Combat Tracker")
        self.manager = CreatureManager()
        self.initUI()
        self.load_state()

    def initUI(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.mainlayout = QHBoxLayout(self.central_widget)

        self.label_layout = QHBoxLayout()
        self.table_layout = QVBoxLayout()

        self.active_init_label = QLabel(self)
        self.active_init_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.active_init_label)

        self.round_counter_label = QLabel(self)
        self.round_counter_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.round_counter_label)

        self.time_counter_label = QLabel(self)
        self.time_counter_label.setStyleSheet("font-size: 18px;")
        self.label_layout.addWidget(self.time_counter_label)

# Create the widget and layout for the table
        self.table_widget = QWidget()
        self.table_widget_layout = QVBoxLayout(self.table_widget)
        self.table_widget_layout.setContentsMargins(0, 0, 0, 0)

# Create the table and model
        self.table = QTableView(self)
        self.table_model = CreatureTableModel(self.manager)
        self.table.setModel(self.table_model)

# Add table to layout
        self.table_widget_layout.addWidget(self.table)

# Now add the label layout and table widget
        self.table_layout = QVBoxLayout()
        self.table_layout.addLayout(self.label_layout)
        self.table_layout.addWidget(self.table_widget)
        self.table_layout.addStretch()

        self.nextprev_layout = QVBoxLayout()
        self.prev_button = QPushButton("Prev", self)
        self.prev_button.clicked.connect(self.prev_turn)
        self.nextprev_layout.addWidget(self.prev_button)
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.next_turn)
        self.nextprev_layout.addWidget(self.next_button)

        self.dam_layout = QVBoxLayout()
        self.creature_list = QListWidget(self)
        self.creature_list.setSelectionMode(QListWidget.MultiSelection)
        self.value_input = QLineEdit(self)
        self.heal_button = QPushButton("Heal", self)
        self.heal_button.clicked.connect(self.heal_selected_creatures)
        self.dam_button = QPushButton("Damage", self)
        self.dam_button.clicked.connect(self.damage_selected_creatures)

        self.heal_dam_layout = QVBoxLayout()
        self.heal_dam_layout.addWidget(self.heal_button)
        self.heal_dam_layout.addWidget(self.value_input)
        self.heal_dam_layout.addWidget(self.dam_button)

        self.creature_list.setFixedWidth(200)
        self.value_input.setFixedWidth(200)
        self.dam_layout.addLayout(self.nextprev_layout)
        self.dam_layout.addWidget(self.creature_list)
        self.dam_layout.addLayout(self.heal_dam_layout)
        self.dam_layout.addStretch()

        self.stat_layout = QVBoxLayout()
        self.statblock = QLabel(self)
        self.statblock.setScaledContents(True)

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
        self.show_hide_butts.addWidget(self.show_img)
        self.show_hide_butts.addWidget(self.hide_img)

        self.list_buttons.addWidget(self.monster_list)
        self.list_buttons.addLayout(self.show_hide_butts)
        self.list_buttons.addStretch()

        self.stat_layout.addWidget(self.statblock)
        self.stat_layout.addLayout(self.list_buttons)
        self.stat_layout.addStretch()

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

        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)

        self.file_menu = self.menu_bar.addMenu("&File")
        self.edit_menu = self.menu_bar.addMenu("&Edit")

        self.filetool_bar = QToolBar("File", self)
        self.addToolBar(self.filetool_bar)

        self.save_action = QAction("Save", self)
        self.save_action.triggered.connect(self.save_state)
        self.file_menu.addAction(self.save_action)

        self.save_as_action = QAction('Save As', self)
        self.save_as_action.triggered.connect(self.save_as)
        self.file_menu.addAction(self.save_as_action)

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

        self.merge_encounters = QAction('Merge Encounters', self)
        self.merge_encounters.triggered.connect(self.merge_encounter)
        self.edit_menu.addAction(self.merge_encounters)
        self.filetool_bar.addAction(self.merge_encounters)

        self.edit_menu.addAction(self.load_enc_button)
        self.edit_menu.addAction(self.add_button)
        self.edit_menu.addAction(self.rmv_button)

    def update_size_constraints(self):
        current_screen = QDesktopWidget().screenNumber(self)
        screen = QDesktopWidget().screenGeometry(current_screen)
        self.screen_width = screen.width()
        self.screen_height = screen.height()
        self.setMaximumSize(self.screen_width, self.screen_height)

    def moveEvent(self, event):
        current_screen = QDesktopWidget().screenNumber(self)
        screen = QDesktopWidget().screenGeometry(current_screen)
        new_width = screen.width()
        new_height = screen.height()

        if (new_width, new_height) != (self.screen_width, self.screen_height):
            self.adjust_table_size()
            self.screen_width = new_width
            self.screen_height = new_height
            self.update_size_constraints()
            self.active_statblock_image(self.sorted_creatures[self.current_turn])
        super().moveEvent(event)

    def center(self):
        frame_geometry = self.frameGeometry()
        screen_center = QDesktopWidget().availableGeometry().center()
        frame_geometry.moveCenter(screen_center)
        self.move(frame_geometry.topLeft())

    def handle_clicked_index(self, index):
        row = index.row()
        col = index.column()
        field = self.table_model.fields[col]
        creature_name = self.table_model.creature_names[row]
        print(f"Clicked {creature_name} - {field}")

    def handle_data_changed(self, topLeft, bottomRight, roles):
        seen = set()
        for row in range(topLeft.row(), bottomRight.row() + 1):
            # Protect against out-of-bounds or stale rows
            if row >= len(self.table_model.creature_names):
                continue

            creature_name = self.table_model.creature_names[row]
            if creature_name not in seen:
                print(f"Data changed for: {creature_name}")
                seen.add(creature_name)

    def toggle_boolean_cell(self, index):
        if not index.isValid():
            return

        row = index.row()
        col = index.column()

        attr = self.table_model.fields[col]
        name = self.table_model.creature_names[row]
        creature = self.manager.creatures[name]
        value = getattr(creature, attr)

        if isinstance(value, bool):
            new_value = not value
            setattr(creature, attr, new_value)
            print(f"Toggled {name}.{attr} → {new_value}")
            self.table_model.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.BackgroundRole])
            self.update_active_init()  # optional for recoloring

    # def handle_data_changed(self, topLeft, bottomRight, roles):
    #     for row in range(topLeft.row(), bottomRight.row() + 1):
    #         creature_name = self.table_model.creature_names[row]
    #         print(f"Data changed for: {creature_name}")
