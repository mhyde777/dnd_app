from PyQt5.QtWidgets import (
    QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QToolBar, QWidget,
    QHBoxLayout, QMainWindow, QListWidget,
    QAction, QMenuBar, QDesktopWidget, QTableView,
    QSizePolicy
)
from PyQt5.QtCore import Qt
from app.app import Application
from app.manager import CreatureManager
from ui.creature_table_model import CreatureTableModel
from ui.spellcasting_dropdown import SpellcastingDropdown
from app.config import use_storage_api_only


class InitiativeTracker(QMainWindow, Application): 
    def __init__(self):
        super().__init__()
        self.center()
        self.update_size_constraints()
        self.setWindowTitle("DnD Combat Tracker")
        self.manager = CreatureManager()
        self.initUI()

        try:
            self.load_state()
            self.table_model.set_fields_from_sample()
            self.table_model.refresh()
            self.update_active_init()  # ✅ <- This is what updates the labels!
            self.pop_lists()
        except Exception as e:
            print(f"[Startup] Failed to load last state: {e}")

    def initUI(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.mainlayout = QHBoxLayout(self.central_widget)

        # === LABEL AREA (Top) ===
        self.label_widget = QWidget()
        self.label_layout = QHBoxLayout(self.label_widget)
        self.label_layout.setContentsMargins(0, 0, 0, 0)

        self.active_init_label = QLabel("Active: None", self)
        self.active_init_label.setStyleSheet("font-size: 18px;")
        self.active_init_label.setMinimumHeight(24)
        self.label_layout.addWidget(self.active_init_label)

        self.round_counter_label = QLabel("Round: 1", self)
        self.round_counter_label.setStyleSheet("font-size: 18px;")
        self.round_counter_label.setMinimumHeight(24)
        self.label_layout.addWidget(self.round_counter_label)

        self.time_counter_label = QLabel("Time: 0 seconds", self)
        self.time_counter_label.setStyleSheet("font-size: 18px;")
        self.time_counter_label.setMinimumHeight(24)
        self.label_layout.addWidget(self.time_counter_label)

        # self.label_layout.addStretch()

        # === TABLE AREA (under labels) ===
        self.table_model = CreatureTableModel(self.manager)
        self.table = QTableView(self)
        self.table.setModel(self.table_model)
        self.table.itemDelegate().commitData.connect(self.on_commit_data)
        self.table.clicked.connect(self.handle_cell_clicked)
# Ensure that the table's size is fixed and matches its content
        self.table.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


        self.table_widget = QWidget()
        self.table_layout = QVBoxLayout(self.table_widget)
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_layout.addWidget(self.label_widget)
        self.table_layout.addWidget(self.table)

        # === SIDEBAR with buttons ===
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

        # === RIGHT PANEL: STATBLOCK VIEW ===
        self.stat_layout = QVBoxLayout()
        self.statblock = QLabel(self)
        self.statblock.setScaledContents(True)

        self.monster_list = QListWidget(self)
        self.monster_list.setSelectionMode(QListWidget.SingleSelection)
        self.monster_list.itemSelectionChanged.connect(self.update_statblock_image)
        self.monster_list.setFixedSize(200, 100)

        self.hide_img = QPushButton("Hide Image", self)
        self.hide_img.clicked.connect(self.hide_statblock)
        self.show_img = QPushButton("Show Image", self)
        self.show_img.clicked.connect(self.show_statblock)

        self.list_buttons = QHBoxLayout()
        self.show_hide_butts = QVBoxLayout()
        self.show_hide_butts.addWidget(self.show_img)
        self.show_hide_butts.addWidget(self.hide_img)
        self.list_buttons.addWidget(self.monster_list)
        self.list_buttons.addLayout(self.show_hide_butts)
        self.list_buttons.addStretch()

        self.stat_layout.addWidget(self.statblock)
        self.stat_layout.addLayout(self.list_buttons)
        self.stat_layout.addStretch()

        # === Wrap and attach all to main layout ===
        self.dam_widget = QWidget()
        self.dam_widget.setLayout(self.dam_layout)

        self.stat_widget = QWidget()
        self.stat_widget.setLayout(self.stat_layout)

        self.mainlayout.addWidget(self.dam_widget, alignment=Qt.AlignLeft)
        self.mainlayout.addWidget(self.table_widget, alignment=Qt.AlignTop)
        self.mainlayout.addStretch()
        self.mainlayout.addWidget(self.stat_widget, alignment=Qt.AlignRight)

        self.setup_menu_and_toolbar()

    def setup_menu_and_toolbar(self):
        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)

        self.file_menu = self.menu_bar.addMenu("&File")
        self.characters_menu = self.file_menu.addMenu("Characters")


        self.edit_menu = self.menu_bar.addMenu("&Edit")
        self.encounter_menu = self.edit_menu.addMenu("Encounters")

        self.filetool_bar = QToolBar("File", self)
        self.addToolBar(self.filetool_bar)

        self.save_action = QAction("Save", self)
        self.save_action.triggered.connect(self.save_state)
        self.file_menu.addAction(self.save_action)

        self.save_as_action = QAction('Save As', self)
        self.save_as_action.triggered.connect(self.save_as_encounter)
        self.file_menu.addAction(self.save_as_action)

        self.initialize_players_action = QAction("Initialize", self)
        self.initialize_players_action.triggered.connect(self.init_players)
        self.edit_menu.addAction(self.initialize_players_action)

        self.load_enc_button = QAction("Load Encounter", self)
        self.load_enc_button.triggered.connect(self.load_encounter)
        self.encounter_menu.addAction(self.load_enc_button)
        self.filetool_bar.addAction(self.load_enc_button)

        self.add_button = QAction("Add Combatant", self)
        self.add_button.triggered.connect(self.add_combatant)
        self.filetool_bar.addAction(self.add_button)

        self.rmv_button = QAction("Remove Combatants", self)
        self.rmv_button.triggered.connect(self.remove_combatant)
        self.filetool_bar.addAction(self.rmv_button)

        self.build_encounter = QAction("Build Encounter", self)
        self.build_encounter.triggered.connect(self.save_encounter)
        self.encounter_menu.addAction(self.build_encounter)

        self.merge_encounters = QAction('Merge Encounters', self)
        self.merge_encounters.triggered.connect(self.merge_encounter)
        self.encounter_menu.addAction(self.merge_encounters)
        self.filetool_bar.addAction(self.merge_encounters)

        # self.edit_menu.addAction(self.load_enc_button)
        self.edit_menu.addAction(self.add_button)
        self.edit_menu.addAction(self.rmv_button)

        self.active_encounters = QAction("Activate/Deactivate Encounters", self)
        self.active_encounters.triggered.connect(self.manage_encounter_statuses)
        self.encounter_menu.addAction(self.active_encounters)

        self.delete_encounters_button = QAction("Delete Encounter", self)
        self.delete_encounters_button.triggered.connect(self.delete_encounters)
        self.encounter_menu.addAction(self.delete_encounters_button)

        self.update_characters_action = QAction("Create/Update Characters", self)
        self.update_characters_action.triggered.connect(self.create_or_update_characters)
        self.characters_menu.addAction(self.update_characters_action)


    def update_size_constraints(self):
        # Get the current screen where the app is being displayed
        current_screen = QDesktopWidget().screenNumber(self)
        screen = QDesktopWidget().screenGeometry(current_screen)
        
        self.screen_width = screen.width()
        self.screen_height = screen.height()
        
        # Set the maximum size to the screen size to avoid going beyond bounds
        self.setMaximumSize(self.screen_width, self.screen_height)
        
        # Optionally set the window size to be full screen on the current screen
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def moveEvent(self, event):
        current_screen = QDesktopWidget().screenNumber(self)
        screen = QDesktopWidget().screenGeometry(current_screen)
        new_width = screen.width()
        new_height = screen.height()

        # Only update if the screen size has changed
        if (new_width, new_height) != (self.screen_width, self.screen_height):
            self.screen_width = new_width
            self.screen_height = new_height
            self.update_size_constraints()  # Update constraints to keep the window within the screen bounds

            # Optionally, center the window on the new screen
            self.center()

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
        # print(f"Clicked {creature_name} - {field}")

    def handle_data_changed(self, topLeft, bottomRight, roles):
        seen = set()
        for row in range(topLeft.row(), bottomRight.row() + 1):
            if row >= len(self.table_model.creature_names):
                continue
            creature_name = self.table_model.creature_names[row]
            if creature_name not in seen:
                # print(f"Data changed for: {creature_name}")
                seen.add(creature_name)

    def toggle_boolean_cell(self, index):
        if not index.isValid():
            return

        row = index.row()
        col = index.column()

        attr = self.table_model.fields[col]

        # ❌ Do nothing if it's the virtual spellbook column
        if attr == "_spellbook":
            return

        name = self.table_model.creature_names[row]
        creature = self.manager.creatures[name]

        value = getattr(creature, attr)

        if isinstance(value, bool):
            new_value = not value
            setattr(creature, attr, new_value)
            self.table_model.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.BackgroundRole])
            self.update_active_init()

    def handle_cell_clicked(self, index):
        attr = self.table_model.fields[index.column()]
        name = self.table_model.creature_names[index.row()]
        creature = self.manager.creatures[name]

        if attr == "_spellbook":
            self.show_spellcasting_dropdown(creature, index)
        else:
            self.toggle_boolean_cell(index)

    def show_spellcasting_dropdown(self, creature, index):
        # Close any existing dropdown
        if hasattr(self, "_active_spell_dropdown") and self._active_spell_dropdown:
            self._active_spell_dropdown.close()

        dropdown = SpellcastingDropdown(creature, self)
        self._active_spell_dropdown = dropdown

        rect = self.table.visualRect(index)
        table_pos = self.table.viewport().mapToGlobal(rect.topLeft())

        dropdown.move(table_pos.x(), table_pos.y() + rect.height())
        dropdown.show()
