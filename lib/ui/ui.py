from typing import Optional
from PyQt5.QtWidgets import (
    QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QToolBar, QWidget,
    QHBoxLayout, QMainWindow, QListWidget,
    QAction, QMenuBar, QDesktopWidget, QTableView,
    QSizePolicy, QMessageBox, QDialog, QDialogButtonBox,
    QMenu, QTextEdit, QGroupBox, QStatusBar, QShortcut, QInputDialog,
    QStackedWidget,
)
from ui.statblock_widget import StatblockWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from app.app import Application
from app.creature import CreatureType
from app.manager import CreatureManager
from ui.creature_table_model import CreatureTableModel
from ui.delegates import CreatureTableDelegate
from ui.spellcasting_dropdown import SpellcastingDropdown
from app.config import player_view_enabled, use_storage_api_only
from ui.conditions_dropdown import ConditionsDropdown, DEFAULT_CONDITIONS

class InitiativeTracker(QMainWindow, Application):
    def __init__(self):
        super().__init__()
        self.center()
        self.update_size_constraints()
        self.setWindowTitle("DnD Combat Tracker")
        self.manager = CreatureManager()
        self.initUI()

        warning = getattr(self, "storage_api_warning", None)
        if warning:
            QMessageBox.warning(self, "Storage API", warning)

        try:
            self.load_state()
            self.table_model.set_fields_from_sample()
            self.table_model.refresh()
            self.update_table()
            self.update_active_init()  # ✅ <- This is what updates the labels!
            self.pop_lists()
        except Exception as e:
            print(f"[Startup] Failed to load last state: {e}")
        self.start_bridge_polling()

    def initUI(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.mainlayout = QHBoxLayout(self.central_widget)

        # === LABEL AREA (Top) ===
        self.label_widget = QWidget()
        self.label_layout = QHBoxLayout(self.label_widget)
        self.label_layout.setContentsMargins(0, 0, 0, 0)

        self.active_init_label = QLabel("Active: None", self)
        self.active_init_label.setObjectName("combatInfoLabel")
        self.active_init_label.setMinimumHeight(24)
        self.label_layout.addWidget(self.active_init_label)

        self.round_counter_label = QLabel("Round: 1", self)
        self.round_counter_label.setObjectName("combatInfoLabel")
        self.round_counter_label.setMinimumHeight(24)
        self.label_layout.addWidget(self.round_counter_label)

        self.time_counter_label = QLabel("Time: 0 seconds", self)
        self.time_counter_label.setObjectName("combatInfoLabel")
        self.time_counter_label.setMinimumHeight(24)
        self.label_layout.addWidget(self.time_counter_label)

        self.label_layout.addStretch()

        self.player_view_toggle = QPushButton("Live Updates: Pause", self)
        self.player_view_toggle.setCheckable(True)
        self.player_view_toggle.setChecked(False)
        self.player_view_toggle.clicked.connect(self.toggle_player_view_live)
        if player_view_enabled():
            self.label_layout.addWidget(self.player_view_toggle)
        else:
            self.player_view_toggle.hide()

        # === TABLE AREA (under labels) ===
        self.table_model = CreatureTableModel(self.manager, parent=self, bridge_owner=self)
        self.table = QTableView(self)
        self.table.setModel(self.table_model)
        self.table_delegate = CreatureTableDelegate(self.table)
        self.table.setItemDelegate(self.table_delegate)
        self.table_delegate.commitData.connect(self.on_commit_data)
        self.table.clicked.connect(self.handle_cell_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.table.setMouseTracking(True)
        self.installEventFilter(self)
        # Ensure that the table's size is fixed and matches its content
        self.table.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.table_widget = QWidget()
        self.table_layout = QVBoxLayout(self.table_widget)
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_layout.addWidget(self.label_widget)
        self.table_layout.addWidget(self.table)

        # === SIDEBAR with buttons ===
        self.dam_layout = QVBoxLayout()

        # -- Turn Controls group --
        turn_group = QGroupBox("Turn Controls")
        turn_group_layout = QVBoxLayout(turn_group)
        self.prev_button = QPushButton("Prev", self)
        self.prev_button.setToolTip("Go to previous turn (Ctrl+Shift+N)")
        self.prev_button.clicked.connect(self.prev_turn)
        turn_group_layout.addWidget(self.prev_button)

        self.next_button = QPushButton("Next", self)
        self.next_button.setToolTip("Advance to next turn (Ctrl+N)")
        self.next_button.clicked.connect(self.next_turn)
        turn_group_layout.addWidget(self.next_button)
        self.dam_layout.addWidget(turn_group)

        # -- Combatants group --
        combatants_group = QGroupBox("Combatants")
        combatants_group_layout = QVBoxLayout(combatants_group)
        combatants_group_layout.setContentsMargins(6, 6, 6, 6)
        self.creature_list = QListWidget(self)
        self.creature_list.setSelectionMode(QListWidget.MultiSelection)
        self.creature_list.setFixedWidth(200)
        self.creature_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        combatants_group_layout.addWidget(self.creature_list)
        combatants_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.dam_layout.addWidget(combatants_group)

        # -- HP Controls group --
        hp_group = QGroupBox("HP Controls")
        hp_group_layout = QVBoxLayout(hp_group)

        self.heal_button = QPushButton("Heal", self)
        self.heal_button.setObjectName("healButton")
        self.heal_button.setToolTip("Heal selected creatures by the entered value")
        self.heal_button.clicked.connect(self.heal_selected_creatures)

        self.value_input = QLineEdit(self)
        self.value_input.setPlaceholderText("HP value...")
        self.value_input.setFixedWidth(200)

        self.dam_button = QPushButton("Damage", self)
        self.dam_button.setObjectName("damageButton")
        self.dam_button.setToolTip("Damage selected creatures by the entered value")
        self.dam_button.clicked.connect(self.damage_selected_creatures)

        hp_group_layout.addWidget(self.heal_button)
        hp_group_layout.addWidget(self.value_input)
        hp_group_layout.addWidget(self.dam_button)
        self.dam_layout.addWidget(hp_group)

        self.dam_layout.addStretch()

        # === RIGHT PANEL: STATBLOCK VIEW ===
        self.stat_layout = QVBoxLayout()

        # Stacked widget: index 0 = image fallback (QLabel), index 1 = JSON renderer
        self.statblock = QLabel(self)
        self.statblock.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.statblock_widget = StatblockWidget(self)
        self.statblock_stack = QStackedWidget(self)
        self.statblock_stack.addWidget(self.statblock)         # 0 — image
        self.statblock_stack.addWidget(self.statblock_widget)  # 1 — JSON
        self.statblock_stack.setCurrentIndex(1)

        self.monster_list = QListWidget(self)
        self.monster_list.setSelectionMode(QListWidget.SingleSelection)
        self.monster_list.itemSelectionChanged.connect(self.update_statblock_image)
        self.monster_list.setFixedSize(200, 100)
        self.monster_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.monster_list.customContextMenuRequested.connect(self._monster_list_context_menu)

        self.hide_img = QPushButton("Hide", self)
        self.hide_img.setToolTip("Hide the statblock panel")
        self.hide_img.clicked.connect(self.hide_statblock)
        self.show_img = QPushButton("Show", self)
        self.show_img.setToolTip("Show the statblock panel")
        self.show_img.clicked.connect(self.show_statblock)

        self.list_buttons = QHBoxLayout()
        self.show_hide_butts = QVBoxLayout()
        self.show_hide_butts.addWidget(self.show_img)
        self.show_hide_butts.addWidget(self.hide_img)
        self.list_buttons.addWidget(self.monster_list)
        self.list_buttons.addLayout(self.show_hide_butts)
        self.list_buttons.addStretch()

        # Statblock fills available space; buttons pinned at bottom
        self.stat_layout.addWidget(self.statblock_stack, stretch=1)
        self.stat_layout.addLayout(self.list_buttons)

        # === Wrap and attach all to main layout ===
        self.dam_widget = QWidget()
        self.dam_widget.setLayout(self.dam_layout)

        self.stat_widget = QWidget()
        self.stat_widget.setLayout(self.stat_layout)

        self.mainlayout.addWidget(self.dam_widget, alignment=Qt.AlignLeft)
        self.mainlayout.addWidget(self.table_widget, alignment=Qt.AlignTop)
        self.mainlayout.addWidget(self.stat_widget, stretch=1)

        self.setup_menu_and_toolbar()

        # === Status Bar ===
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

    def show_status_message(self, msg: str, timeout_ms: int = 4000):
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(msg, timeout_ms)

    def _monster_list_context_menu(self, pos):
        menu = QMenu(self)
        import_action = menu.addAction("Import Statblock...")
        action = menu.exec_(self.monster_list.mapToGlobal(pos))
        if action == import_action:
            self.open_import_statblock_dialog()

    def setup_menu_and_toolbar(self):
        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)

        self.file_menu = self.menu_bar.addMenu("&File")
        self.characters_menu = self.file_menu.addMenu("Characters")

        self.edit_menu = self.menu_bar.addMenu("&Edit")
        self.encounter_menu = self.menu_bar.addMenu("&Encounters")
        self.images_menu = self.menu_bar.addMenu("&Images")
        self.monsters_menu = self.menu_bar.addMenu("&Parsers")

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

        self.manage_images_action = QAction("Mange Images", self)
        self.manage_images_action.triggered.connect(self.manage_images)
        self.images_menu.addAction(self.manage_images_action)

        self.import_statblock_action = QAction("Import Statblock...", self)
        self.import_statblock_action.triggered.connect(self.open_import_statblock_dialog)
        self.monsters_menu.addAction(self.import_statblock_action)

        self.import_spell_action = QAction("Import Spell...", self)
        self.import_spell_action.triggered.connect(self.open_import_spell_dialog)
        self.monsters_menu.addAction(self.import_spell_action)

        # -- Keyboard shortcuts --
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))

        self.next_turn_action = QAction("Next Turn", self)
        self.next_turn_action.setShortcut(QKeySequence("Ctrl+N"))
        self.next_turn_action.triggered.connect(self.next_turn)
        self.edit_menu.addAction(self.next_turn_action)

        self.prev_turn_action = QAction("Previous Turn", self)
        self.prev_turn_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.prev_turn_action.triggered.connect(self.prev_turn)
        self.edit_menu.addAction(self.prev_turn_action)

        # -- Toolbar tooltips --
        self.load_enc_button.setToolTip("Load a saved encounter")
        self.add_button.setToolTip("Add new combatants to the encounter")
        self.rmv_button.setToolTip("Remove combatants from the encounter")
        self.merge_encounters.setToolTip("Merge another encounter into the current one")
        self.save_action.setToolTip("Save current state (Ctrl+S)")
        self.save_as_action.setToolTip("Save current encounter as a new file")

    def update_size_constraints(self):
        # Get the current screen where the app is being displayed
        current_screen = QDesktopWidget().screenNumber(self)
        screen = QDesktopWidget().availableGeometry(current_screen)

        self.screen_width = screen.width()
        self.screen_height = screen.height()

    def moveEvent(self, event):
        current_screen = QDesktopWidget().screenNumber(self)
        screen = QDesktopWidget().availableGeometry(current_screen)
        new_width = screen.width()
        new_height = screen.height()

        # Update stored screen dimensions when the screen changes
        if (new_width, new_height) != (self.screen_width, self.screen_height):
            self.screen_width = new_width
            self.screen_height = new_height

        super().moveEvent(event)

    def center(self):
        frame_geometry = self.frameGeometry()
        current_screen = QDesktopWidget().screenNumber(self)
        screen_center = QDesktopWidget().availableGeometry(current_screen).center()
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
            return
        if attr == "_conditions":
            self.show_conditions_dropdown(creature, index)
            return
        if attr == "_curr_hp":
            self.show_hp_dropdown(creature, index)
            return

        self.toggle_boolean_cell(index)
    
    def _get_creature_from_index(self, index):
        if not index or not index.isValid():
            return None, None
        row = index.row()
        if row < 0 or row >= len(self.table_model.creature_names):
            return None, None
        name = self.table_model.creature_names[row]
        creature = self.manager.creatures.get(name)
        return name, creature

    def show_hp_dropdown(self, creature, index):
        menu = QMenu(self)

        set_temp_action = menu.addAction("Set Temp HP")
        set_max_bonus_action = menu.addAction("Set Max HP Bonus")
        clear_bonus_action = menu.addAction("Clear Temp/Bonus HP")

        pos = self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft())
        chosen = menu.exec_(pos)

        if chosen == set_temp_action:
            current = int(getattr(creature, "temp_hp", 0) or 0)
            value, ok = QInputDialog.getInt(
                self,
                f"Temp HP: {getattr(creature, 'name', '')}",
                "Temporary HP:",
                current,
                0,
                9999,
                1,
            )
            if ok:
                creature.temp_hp = value
                self.update_table()
            return

        if chosen == set_max_bonus_action:
            current = int(getattr(creature, "max_hp_bonus", 0) or 0)
            value, ok = QInputDialog.getInt(
                self,
                f"Max HP Bonus: {getattr(creature, 'name', '')}",
                "Bonus Max HP (can be negative):",
                current,
                -9999,
                9999,
                1,
            )
            if ok:
                creature.max_hp_bonus = value
                max_total = int(getattr(creature, "effective_max_hp", creature.max_hp) or 0)
                creature.curr_hp = min(int(getattr(creature, "curr_hp", 0) or 0), max_total)
                self._enqueue_bridge_set_hp(getattr(creature, "name", ""), creature.curr_hp)
                self.update_table()
            return

        if chosen == clear_bonus_action:
            creature.temp_hp = 0
            creature.max_hp_bonus = 0
            capped_hp = int(getattr(creature, "max_hp", 0) or 0)
            creature.curr_hp = min(int(getattr(creature, "curr_hp", 0) or 0), capped_hp)
            self._enqueue_bridge_set_hp(getattr(creature, "name", ""), creature.curr_hp)
            self.update_table()


    def _show_notes_editor(self, title: str, text: str) -> Optional[str]:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        editor = QTextEdit(dialog)
        editor.setPlainText(text or "")
        editor.setMinimumWidth(360)
        editor.setMinimumHeight(160)
        layout.addWidget(editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            return editor.toPlainText()
        return None

    def _refresh_player_view(self):
        if hasattr(self, "player_view_live") and not self.player_view_live:
            try:
                self.player_view_snapshot = self._build_player_view_payload()
            except Exception:
                pass

    def _remove_combatant_by_name(self, name: str):
        if not name:
            return
        self.manager.rm_creatures(name)
        self.manager.sort_creatures()
        self.build_turn_order()
        self.update_table()
        self.update_active_ui()

        active_name = self.active_name()
        if active_name:
            creature = self.manager.creatures.get(active_name)
            if creature and getattr(creature, "_type", None) == CreatureType.MONSTER:
                self.active_statblock_image(creature)
            else:
                self.statblock.clear()
        else:
            self.statblock.clear()

    def _set_active_turn_by_name(self, name: str):
        if not name:
            return
        self.build_turn_order()
        if name in self.turn_order:
            self.current_idx = self.turn_order.index(name)
            self.current_creature_name = name
            self.update_active_ui()

    def show_table_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return

        name, creature = self._get_creature_from_index(index)
        if creature is None:
            return

        menu = QMenu(self)

        if getattr(creature, "_type", None) == CreatureType.MONSTER:
            visible = bool(getattr(creature, "player_visible", True))
            visibility_label = "Hide from Player View" if visible else "Reveal to Player View"
            visibility_action = menu.addAction(visibility_label)
        else:
            visibility_action = None

        edit_public_action = menu.addAction("Edit Public Notes...")
        edit_private_action = menu.addAction("Edit Private Notes...")
        menu.addSeparator()
        clear_conditions_action = menu.addAction("Clear Conditions")
        set_active_action = menu.addAction("Set as Active Turn")
        remove_action = menu.addAction("Remove Combatant")

        chosen = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if visibility_action and chosen == visibility_action:
            creature.player_visible = not bool(getattr(creature, "player_visible", True))
            self.table_model.refresh()
            self.update_table()
            self._refresh_player_view()
            return

        if chosen == edit_public_action:
            updated = self._show_notes_editor("Edit Public Notes", getattr(creature, "public_notes", "") or "")
            if updated is not None:
                creature.public_notes = updated
                self.table_model.refresh()
                self.update_table()
                self._refresh_player_view()
            return

        if chosen == edit_private_action:
            updated = self._show_notes_editor("Edit Private Notes", getattr(creature, "notes", "") or "")
            if updated is not None:
                creature.notes = updated
                self.table_model.refresh()
                self.update_table()
            return

        if chosen == clear_conditions_action:
            removed = list(getattr(creature, "conditions", []) or [])
            creature.conditions = []
            self.table_model.refresh()
            self.update_table()
            if hasattr(self, "_enqueue_bridge_condition_delta"):
                try:
                    self._enqueue_bridge_condition_delta(creature, [], removed)
                except Exception:
                    pass
            return

        if chosen == remove_action:
            self._remove_combatant_by_name(name)
            return

    def toggle_player_view_live(self, checked):
        paused = bool(checked)
        if hasattr(self, "set_player_view_paused"):
            self.set_player_view_paused(paused)
        self.player_view_toggle.setText(
            "Live Updates: Resume" if paused else "Live Updates: Pause"
        )

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

    def show_conditions_dropdown(self, creature, index):
        # Close any existing conditions dropdown
        if hasattr(self, "_active_conditions_dropdown") and self._active_conditions_dropdown:
            try:
                self._active_conditions_dropdown.close()
            except Exception:
                pass

        dropdown = ConditionsDropdown(creature, parent=self, condition_names=DEFAULT_CONDITIONS)
        self._active_conditions_dropdown = dropdown

        rect = self.table.visualRect(index)
        table_pos = self.table.viewport().mapToGlobal(rect.topLeft())

        dropdown.move(table_pos.x(), table_pos.y() + rect.height())
        dropdown.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            # Clear table selection
            if hasattr(self, "table"):
                self.table.clearSelection()
                self.table.setCurrentIndex(self.table.model().index(-1, -1))

            # Also close any open dropdowns
            if hasattr(self, "_active_conditions_dropdown"):
                try:
                    self._active_conditions_dropdown.close()
                except Exception:
                    pass
                self._active_conditions_dropdown = None

            if hasattr(self, "_active_spell_dropdown"):
                try:
                    self._active_spell_dropdown.close()
                except Exception:
                    pass
                self._active_spell_dropdown = None

            return  # swallow Esc so it doesn't propagate

        super().keyPressEvent(event)
    
    def closeEvent(self, event):
        server = getattr(self, "player_view_server", None)
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass
        local_bridge = getattr(self, "local_bridge", None)
        if local_bridge is not None:
            try:
                local_bridge.stop()
            except Exception:
                pass
        stream_stop = getattr(self, "bridge_stream_stop", None)
        if stream_stop is not None:
            try:
                stream_stop.set()
            except Exception:
                pass
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == event.MouseButtonPress:
            # If the click target is NOT inside the table, clear selection
            if hasattr(self, "table"):
                table_rect = self.table.rect()
                table_pos = self.table.mapFromGlobal(event.globalPos())

                if not table_rect.contains(table_pos):
                    self.table.clearSelection()
                    self.table.setCurrentIndex(self.table.model().index(-1, -1))

        return super().eventFilter(obj, event)
