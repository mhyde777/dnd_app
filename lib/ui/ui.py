import os
import subprocess
import sys
from time import monotonic
from typing import Optional
from PyQt5.QtWidgets import (
    QApplication, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QToolBar, QWidget,
    QHBoxLayout, QMainWindow, QListWidget,
    QAction, QMenuBar, QDesktopWidget, QTableView,
    QSizePolicy, QMessageBox, QDialog, QDialogButtonBox,
    QMenu, QTextEdit, QGroupBox, QStatusBar, QShortcut,
    QWidgetAction, QFormLayout, QSpinBox, QFrame,
    QDockWidget, QScrollArea, QTabWidget,
)
from ui.statblock_widget import StatblockWidget
from PyQt5.QtCore import (
    Qt, QByteArray, QEvent, QItemSelectionModel, QObject, QTimer, pyqtSignal,
)
from PyQt5.QtGui import QFont, QIntValidator, QKeySequence
from app.app import Application
from app import update_check
from app.config import update_check_enabled
from app.version import __version__
from app.creature import CreatureType
from app.manager import CreatureManager
from app import settings as app_settings
from ui.creature_table_model import CreatureTableModel
from ui.delegates import CreatureTableDelegate
from ui import colors
from ui.banner import BannerArea
from ui.icons import icon_for
from ui.layout_settings_dialog import (
    PANEL_REGISTRY, load_panel_layout, save_panel_layout,
)
from ui.control_sections_dialog import (
    ControlSectionsDialog,
    DEFAULT_CONTROL_SECTIONS,
    load_control_sections,
    ordered_all,
    save_control_sections,
)
from ui.notifications import report_error, reposition_toasts, toast
from ui.shortcut_settings_dialog import (
    FIXED_SHORTCUTS,
    SHORTCUT_SCHEMA,
    ShortcutSettingsDialog,
    ZOOM_IN_ALIAS,
    defaults as shortcut_defaults,
    load as load_shortcuts,
)
from ui.spellcasting_dropdown import SpellcastingDropdown
from ui.ability_uses_dropdown import AbilityUsesDropdown
from ui.conditions_dropdown import ConditionsDropdown, DEFAULT_CONDITIONS

# Bumped whenever the set of docks/toolbars changes, so a layout saved by an
# older build is discarded instead of restoring into a broken arrangement.
LAYOUT_VERSION = 1

# How long after the first show the configured panel widths keep overriding
# whatever Qt lays out. The window manager's maximize lands a few frames after
# show() and is what knocks panels out of their configured widths, so this has
# to outlast it comfortably.
_LAYOUT_SETTLE_MS = 1500

# Dock resizes landing this soon after a window resize are Qt redistributing
# space, not the user dragging a separator.
_WINDOW_RESIZE_GRACE = 0.4


class _DockResizeWatcher(QObject):
    """
    Notices the user dragging a dock separator.

    A dock also gets resized whenever the window does, and those widths are
    Qt's arithmetic rather than a choice — `_dock_resized` filters those out.
    """

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Resize
            and event.oldSize().width() > 0
            and event.size().width() != event.oldSize().width()
        ):
            self._window._dock_resized(obj)
        return False


class InitiativeTracker(QMainWindow, Application):
    # Emitted from the update-check worker thread. It has to be a signal:
    # QTimer.singleShot() called off the GUI thread creates its timer in a
    # thread with no event loop, so it never fires and the banner silently
    # never appears.
    update_available = pyqtSignal(str)

    # The bridge's SSE stream delivers snapshots on a worker thread. Handing
    # them over with QTimer.singleShot() does not work -- the timer is created
    # in a thread with no event loop, so it never fires and every streamed
    # snapshot was silently dropped. Signals queue across threads correctly.
    bridge_snapshot_received = pyqtSignal(object)
    bridge_status_changed = pyqtSignal(str)

    # Result of a user-requested update check, marshalled off the worker thread.
    update_check_finished = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.center()
        self.update_size_constraints()
        self.setWindowTitle("DnD Combat Tracker")
        self.manager = CreatureManager()
        self._allow_panel_drag = False
        self._panel_layout = None
        self.initUI()

        # Layout must be applied after every dock exists, or placing them
        # silently no-ops for docks that weren't created yet.
        self._layout_restored = self.restore_layout()

        warning = getattr(self, "storage_api_warning", None)
        if warning:
            QMessageBox.warning(self, "Storage API", warning)

        try:
            self.load_state()
            self.table_model.set_fields_from_sample()
            self.table_model.refresh()
            self.update_table()
            self.update_active_init()
            self.pop_lists()
        except Exception as e:
            report_error(
                self, "Could Not Load Last Session",
                "The app started, but your last combat state could not be "
                "restored. You can load an encounter from the Encounters menu.",
                e,
            )
        self.bridge_snapshot_received.connect(
            self._set_bridge_snapshot, Qt.QueuedConnection
        )
        self.bridge_status_changed.connect(
            self.set_bridge_status, Qt.QueuedConnection
        )
        self.update_check_finished.connect(
            self._on_manual_update_check, Qt.QueuedConnection
        )
        self.start_bridge_polling()
        self.check_for_updates()
        self.start_version_housekeeping()
        self.verify_new_version()

    def check_for_updates(self):
        """Tell the user when a newer release exists. Never blocks, never nags.

        Runs off the GUI thread and fails silently -- someone playing offline
        should not get a network error about updates mid-session.
        """
        if not update_check_enabled():
            return

        try:
            from app.update_check import check_in_background
            # Queued across threads by Qt, so the banner is built on the GUI
            # thread even though the check finishes on a worker.
            self.update_available.connect(
                self._show_update_banner, Qt.QueuedConnection
            )
            check_in_background(self.update_available.emit)
        except Exception as exc:
            self._log(f"[DBG] Update check could not start: {exc}")

    def _show_update_banner(self, version: str):
        from app.version import __version__

        self.show_banner(
            "update-available",
            f"Version {version} is available — you're on {__version__}. "
            "Nothing installs unless you choose to.",
            level="info",
            action_label=f"Get {version}",
            action=lambda: self.open_update_dialog(version),
        )

    def open_update_dialog(self, version: str, release: dict = None):
        """What changed, and the download for this platform if there is one.

        The release payload is re-fetched when it wasn't passed in: the startup
        check only carries the version string across the thread boundary, and
        the asset list is what decides whether a download is even offered.
        """
        from ui.update_dialog import UpdateDialog

        if release is None:
            release = update_check.fetch_latest_release()
        UpdateDialog(self, version=version, release=release).exec_()

    def check_for_updates_now(self):
        """Help → Check for Updates. Answers either way, unlike the startup check."""
        self.show_status_message("Checking for updates…")
        update_check.latest_in_background(self.update_check_finished.emit)

    def _on_manual_update_check(self, release):
        """Result of a check the user asked for, back on the GUI thread."""
        if not release:
            self.notify(
                "Could not reach GitHub, or there are no published releases yet",
                "warning",
            )
            return

        tag = release.get("tag_name") or release.get("name") or ""
        if tag and update_check.is_newer(tag):
            self._show_update_banner(tag)
            self.open_update_dialog(tag, release)
        else:
            self.notify(f"You are on the latest version ({__version__})", "success")

    def initUI(self):
        # Layout model: the initiative table is the fixed centre of the window;
        # every supporting panel is a QDockWidget so the user can resize, float,
        # re-dock or close it. Arrangement is saved on exit and restored on
        # launch, and View → Reset Panel Layout puts it all back.
        self._build_central_table_area()
        self._build_controls_dock()
        self._build_statblock_dock()

        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)

        self.setup_menu_and_toolbar()
        self._build_status_bar()

        # Sequences are not set here -- apply_shortcuts() reads them from the
        # registry so the user's bindings win. These only wire key to command.
        self.filter_shortcut = QShortcut(self)
        self.filter_shortcut.activated.connect(self.focus_creature_filter)

        # Statblock legibility without resizing the panel.
        self.zoom_in_shortcut = QShortcut(self)
        self.zoom_in_shortcut.activated.connect(self.statblock_widget.zoom_in)
        self.zoom_out_shortcut = QShortcut(self)
        self.zoom_out_shortcut.activated.connect(self.statblock_widget.zoom_out)
        self.zoom_reset_shortcut = QShortcut(self)
        self.zoom_reset_shortcut.activated.connect(self.statblock_widget.reset_zoom)
        # Ctrl+= is the unshifted twin of Ctrl++; see ZOOM_IN_ALIAS.
        self.zoom_in_alias_shortcut = QShortcut(self)
        self.zoom_in_alias_shortcut.activated.connect(self.statblock_widget.zoom_in)

        self.apply_shortcuts()

    # ---- layout construction ------------------------------------------------

    def _build_central_table_area(self):
        """Combat info labels + the initiative table, as the central widget."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.mainlayout = QVBoxLayout(self.central_widget)
        self.mainlayout.setContentsMargins(8, 8, 8, 8)
        self.mainlayout.setSpacing(6)

        # Persistent notifications live above the table, where you're looking.
        self.banner_area = BannerArea(self)
        self.mainlayout.addWidget(self.banner_area)

        # === LABEL AREA (Top) ===
        self.label_widget = QWidget()
        self.label_layout = QHBoxLayout(self.label_widget)
        self.label_layout.setContentsMargins(0, 0, 0, 0)
        self.label_layout.setSpacing(18)

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

        # === TABLE ===
        self.table_model = CreatureTableModel(self.manager, parent=self, bridge_owner=self)
        self.table = QTableView(self)
        self.table.setModel(self.table_model)
        self.table_delegate = CreatureTableDelegate(self.table)
        self.table.setItemDelegate(self.table_delegate)
        self.table_delegate.commitData.connect(self.on_commit_data)
        # When a cell editor closes, replay any bridge snapshot that was deferred
        # while editing so in-progress notes aren't clobbered by layoutChanged.
        self.table_delegate.closeEditor.connect(self._flush_pending_bridge_snapshot)
        self.table.clicked.connect(self.handle_cell_clicked)
        # Targeting is per combatant, so a click anywhere in the row selects
        # the whole row -- the row *is* the creature.
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.table.setMouseTracking(True)
        self.table.setHorizontalScrollMode(QTableView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QTableView.ScrollPerPixel)
        # The table grows with the window instead of being pinned to its content
        # size, so a long initiative order scrolls rather than running off-screen.
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.installEventFilter(self)

        # Column widths the user dragged, keyed by field name. Restored here so
        # the first adjust_table_size() already honours them.
        self._sizing_columns = False
        self._user_column_widths = dict(
            app_settings.get("table_column_widths") or {}
        )
        header = self.table.horizontalHeader()
        header.setSectionsMovable(False)
        header.sectionResized.connect(self._on_column_resized)
        # Watch the container, not the table: the table's own width is capped
        # to its columns, so it stops changing once it fits and would never
        # notice the window or a dock giving it more room.
        self.central_widget.installEventFilter(self)
        # The viewport still moves on its own when a scrollbar appears.
        self.table.viewport().installEventFilter(self)

        # Rows picked in the table are the same targets as names ticked in the
        # combatant list; keep the two views showing one selection.
        self._syncing_selection = False
        self._clearing_table_selection = False
        self.table.selectionModel().selectionChanged.connect(
            self._mirror_table_selection_to_list
        )

        self.mainlayout.addWidget(self.label_widget)
        # The table takes the space it needs and no more: _fit_table_height()
        # caps it at the height of the rows it actually holds, and this spacer
        # -- expanding, but with no stretch of its own -- absorbs whatever is
        # left rather than the table running on as empty rows. Capping without
        # the stretch factor would leave the table at its size hint instead.
        self.mainlayout.addWidget(self.table, stretch=1)
        self.mainlayout.addStretch(0)

        # Kept as an alias: older code and saved dock state refer to table_widget.
        self.table_widget = self.central_widget

    def _build_controls_dock(self):
        """Left dock: turn controls, combatant picker, HP entry and HP mods."""
        self.dam_layout = QVBoxLayout()
        self.dam_layout.setContentsMargins(8, 8, 8, 8)
        self.dam_layout.setSpacing(8)

        # -- Turn Controls group --
        turn_group = QGroupBox("Turn Controls")
        turn_group_layout = QHBoxLayout(turn_group)
        self.prev_button = QPushButton("◀  Prev", self)
        self.prev_button.setToolTip("Go to previous turn (Ctrl+Shift+N)")
        self.prev_button.clicked.connect(self.prev_turn)
        turn_group_layout.addWidget(self.prev_button)

        self.next_button = QPushButton("Next  ▶", self)
        self.next_button.setObjectName("primaryButton")
        self.next_button.setToolTip("Advance to next turn (Ctrl+N)")
        self.next_button.clicked.connect(self.next_turn)
        turn_group_layout.addWidget(self.next_button)

        # -- Combatants group --
        combatants_group = QGroupBox("Combatants")
        combatants_group_layout = QVBoxLayout(combatants_group)
        combatants_group_layout.setContentsMargins(6, 6, 6, 6)
        self.creature_filter = QLineEdit(self)
        self.creature_filter.setPlaceholderText("Filter combatants… (Ctrl+F)")
        self.creature_filter.setClearButtonEnabled(True)
        self.creature_filter.textChanged.connect(self._filter_creature_list)
        combatants_group_layout.addWidget(self.creature_filter)

        self.creature_list = QListWidget(self)
        self.creature_list.setSelectionMode(QListWidget.MultiSelection)
        self.creature_list.setMinimumWidth(180)
        # Height follows the number of combatants (see _fit_creature_list_height);
        # an empty list should not push the HP controls to the bottom of the dock.
        self.creature_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.creature_list.setToolTip(
            "Select one or more combatants, then use the HP controls below.\n"
            "Click to add or remove one, Shift+click to take a whole run.\n"
            "Selecting rows in the initiative table does the same thing."
        )
        self.creature_list.itemSelectionChanged.connect(
            self._mirror_list_selection_to_table
        )
        # MultiSelection has no range gesture of its own; _list_shift_click
        # supplies one, anchored on the last plainly-clicked row.
        self._list_anchor_row = None
        self._list_range_rows = set()
        self.creature_list.viewport().installEventFilter(self)
        combatants_group_layout.addWidget(self.creature_list)

        selection_row = QHBoxLayout()
        selection_row.setContentsMargins(0, 0, 0, 0)
        selection_row.setSpacing(6)
        select_all_btn = QPushButton("Select All")
        select_all_btn.setToolTip("Select every visible combatant")
        select_all_btn.clicked.connect(self._select_all_visible_creatures)
        clear_sel_btn = QPushButton("Clear")
        clear_sel_btn.setToolTip("Clear the combatant selection")
        clear_sel_btn.clicked.connect(self.creature_list.clearSelection)
        selection_row.addWidget(select_all_btn)
        selection_row.addWidget(clear_sel_btn)
        combatants_group_layout.addLayout(selection_row)
        self._fit_creature_list_height()

        # -- HP Controls group --
        # Ordered heal / value / damage so the destructive button isn't the one
        # sitting under the cursor after typing a number.
        hp_group = QGroupBox("HP Controls")
        hp_group_layout = QVBoxLayout(hp_group)
        hp_group_layout.setSpacing(5)

        self.value_input = QLineEdit(self)
        self.value_input.setPlaceholderText("HP value…")
        self.value_input.setMinimumWidth(180)
        self.value_input.setToolTip("Enter HP value — Enter to damage, Shift+Enter to heal")
        self.value_input.installEventFilter(self)
        hp_group_layout.addWidget(self.value_input)

        hp_button_row = QHBoxLayout()
        hp_button_row.setSpacing(6)

        self.heal_button = QPushButton("Heal", self)
        self.heal_button.setObjectName("healButton")
        self.heal_button.setToolTip("Heal selected creatures by the entered value (Shift+Enter)")
        self.heal_button.clicked.connect(self.heal_selected_creatures)
        hp_button_row.addWidget(self.heal_button)

        self.dam_button = QPushButton("Damage", self)
        self.dam_button.setObjectName("damageButton")
        self.dam_button.setToolTip("Damage selected creatures by the entered value (Enter)")
        self.dam_button.clicked.connect(self.damage_selected_creatures)
        hp_button_row.addWidget(self.dam_button)

        hp_group_layout.addLayout(hp_button_row)

        # -- HP Mods group (Temp HP + Max HP Bonus, multi-creature) --
        hp_mods_group = QGroupBox("HP Mods")
        hp_mods_layout = QFormLayout(hp_mods_group)
        hp_mods_layout.setContentsMargins(6, 6, 6, 6)
        hp_mods_layout.setSpacing(4)
        hp_mods_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.temp_hp_spin = QSpinBox(self)
        self.temp_hp_spin.setRange(0, 9999)
        self.temp_hp_spin.setMinimumWidth(80)
        self.temp_hp_spin.setToolTip("Temporary HP to set on selected creatures")

        self.max_hp_bonus_spin = QSpinBox(self)
        self.max_hp_bonus_spin.setRange(-9999, 9999)
        self.max_hp_bonus_spin.setMinimumWidth(80)
        self.max_hp_bonus_spin.setToolTip("Max HP bonus/penalty to set on selected creatures")

        hp_mods_layout.addRow("Temp HP:", self.temp_hp_spin)
        hp_mods_layout.addRow("Max Bonus:", self.max_hp_bonus_spin)

        hp_mods_btn_row = QWidget()
        hp_mods_btn_layout = QHBoxLayout(hp_mods_btn_row)
        hp_mods_btn_layout.setContentsMargins(0, 2, 0, 0)
        hp_mods_btn_layout.setSpacing(6)
        self.hp_mods_apply_button = QPushButton("Apply")
        self.hp_mods_apply_button.clicked.connect(self.apply_hp_mods_to_selected)
        self.hp_mods_clear_button = QPushButton("Clear")
        self.hp_mods_clear_button.clicked.connect(lambda: self.apply_hp_mods_to_selected(clear=True))
        hp_mods_btn_layout.addWidget(self.hp_mods_apply_button)
        hp_mods_btn_layout.addWidget(self.hp_mods_clear_button)
        hp_mods_layout.addRow(hp_mods_btn_row)

        # Which of these are shown, and in what order, is the user's call.
        # apply_control_sections() puts them into dam_layout.
        self._control_sections = {
            "turn_controls": turn_group,
            "combatants":    combatants_group,
            "hp_controls":   hp_group,
            "hp_mods":       hp_mods_group,
        }

        self.dam_widget = QWidget()
        self.dam_widget.setLayout(self.dam_layout)
        self.dam_widget.setMinimumWidth(210)
        self.apply_control_sections()

        # Scrolled, so shrinking the dock hides nothing outright.
        controls_scroll = QScrollArea()
        controls_scroll.setWidget(self.dam_widget)
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.NoFrame)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.controls_dock = QDockWidget("Combat Controls", self)
        self.controls_dock.setObjectName("controlsDock")  # required by saveState()
        self.controls_dock.setWidget(controls_scroll)
        self.controls_dock.setMinimumWidth(230)
        self.controls_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.controls_dock)

    # The combatant list is sized to its contents, clamped so a single
    # combatant doesn't leave a sliver and a big fight doesn't eat the dock.
    _CREATURE_LIST_MIN_ROWS = 3
    _CREATURE_LIST_MAX_ROWS = 14

    def _fit_creature_list_height(self):
        """Match the list's height to the number of visible combatants."""
        listw = getattr(self, "creature_list", None)
        if listw is None:
            return

        row_height = listw.sizeHintForRow(0) if listw.count() else 0
        if row_height <= 0:
            row_height = listw.fontMetrics().height() + 6

        visible = sum(
            1 for row in range(listw.count()) if not listw.item(row).isHidden()
        )
        rows = min(
            max(visible, self._CREATURE_LIST_MIN_ROWS), self._CREATURE_LIST_MAX_ROWS
        )
        listw.setFixedHeight(rows * row_height + 2 * listw.frameWidth() + 4)

    def apply_control_sections(self, config: list = None):
        """Lay the Combat Controls dock out from the saved section config.

        Hidden sections stay in the layout rather than being reparented out of
        it -- a hidden widget takes no space, and showing one again is then a
        setVisible() instead of a rebuild.
        """
        if config is None:
            config = load_control_sections()
        visible = set(config)

        layout = self.dam_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()

        for key in ordered_all(config):
            section = self._control_sections.get(key)
            if section is None:
                continue
            layout.addWidget(section)
            section.setVisible(key in visible)

        # Spare height collects under the last section rather than being handed
        # to the combatant list and dragging the HP controls to the bottom.
        layout.addStretch(1)

        # The dock can be much shorter now; re-fit what is sized to content.
        if "combatants" in visible:
            self._fit_creature_list_height()

    def _filter_creature_list(self, text: str):
        """Hide non-matching rows; a hidden row keeps its selection state."""
        needle = (text or "").strip().lower()
        for row in range(self.creature_list.count()):
            item = self.creature_list.item(row)
            hidden = bool(needle) and needle not in item.text().lower()
            item.setHidden(hidden)
            if hidden:
                # Never leave a filtered-out combatant selected — otherwise
                # damage lands on something the user can no longer see.
                item.setSelected(False)
        self._fit_creature_list_height()

    def _select_all_visible_creatures(self):
        for row in range(self.creature_list.count()):
            item = self.creature_list.item(row)
            if not item.isHidden():
                item.setSelected(True)

    def _list_shift_click(self, event) -> bool:
        """Shift+click the combatant list to take the run between two names.

        Plain clicks keep MultiSelection's add-and-remove behaviour, which is
        what you want for picking scattered combatants -- but Qt offers no
        range gesture in that mode, so this adds one. The range *adds* to the
        selection rather than replacing it, so extending a pick can never wipe
        one you built up click by click.

        Returns True when the click was handled and Qt should not also toggle
        the item under the cursor.
        """
        item = self.creature_list.itemAt(event.pos())
        if item is None:
            return False

        row = self.creature_list.row(item)
        anchor = self._list_anchor_row
        if not (event.modifiers() & Qt.ShiftModifier) or anchor is None:
            # Every ordinary click becomes the anchor for the next Shift+click,
            # and ends whatever run the last one drew.
            self._list_anchor_row = row
            self._list_range_rows = set()
            return False

        first, last = sorted((anchor, row))
        wanted = {
            index
            for index in range(first, last + 1)
            # A combatant filtered out of view is not a valid target.
            if self.creature_list.item(index) is not None
            and not self.creature_list.item(index).isHidden()
        }
        # Only the previous run's own rows are given back, so a shorter
        # Shift+click shrinks the run without disturbing picks made by hand.
        stale = self._list_range_rows - wanted

        # One mirror pass for the whole range instead of one per item.
        self._syncing_selection = True
        try:
            for index in wanted:
                self.creature_list.item(index).setSelected(True)
            for index in stale:
                candidate = self.creature_list.item(index)
                if candidate is not None:
                    candidate.setSelected(False)
        finally:
            self._syncing_selection = False

        self._list_range_rows = wanted
        self._mirror_list_selection_to_table()
        # The anchor stays put, so repeated Shift+clicks re-extend from it.
        return True

    # Kept shorter than the combatant list: this is a picker, and every row it
    # takes is a row the statblock above it loses.
    _MONSTER_LIST_MIN_ROWS = 2
    _MONSTER_LIST_MAX_ROWS = 6

    def _fit_monster_list_height(self):
        """Match the monster picker's height to the monsters in the fight."""
        listw = getattr(self, "monster_list", None)
        if listw is None:
            return

        row_height = listw.sizeHintForRow(0) if listw.count() else 0
        if row_height <= 0:
            row_height = listw.fontMetrics().height() + 6

        rows = min(
            max(listw.count(), self._MONSTER_LIST_MIN_ROWS),
            self._MONSTER_LIST_MAX_ROWS,
        )
        listw.setFixedHeight(rows * row_height + 2 * listw.frameWidth() + 4)

    def _mirror_table_selection_to_list(self, *_):
        """Rows picked in the table become the HP controls' targets."""
        if self._syncing_selection or self._clearing_table_selection:
            return

        names = {
            self.table_model.creature_names[index.row()]
            for index in self.table.selectionModel().selectedRows()
            if 0 <= index.row() < len(self.table_model.creature_names)
        }
        self._syncing_selection = True
        try:
            for row in range(self.creature_list.count()):
                item = self.creature_list.item(row)
                # A combatant filtered out of the list is not a valid target,
                # so never select one back into view.
                item.setSelected(not item.isHidden() and item.text() in names)
        finally:
            self._syncing_selection = False

    def _mirror_list_selection_to_table(self):
        """Names ticked in the list light up their rows in the table."""
        if self._syncing_selection:
            return

        names = {
            self.creature_list.item(row).text()
            for row in range(self.creature_list.count())
            if self.creature_list.item(row).isSelected()
        }
        model = self.table.model()
        selection = self.table.selectionModel()
        if model is None or selection is None:
            return

        self._syncing_selection = True
        try:
            selection.clearSelection()
            flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
            for row, name in enumerate(self.table_model.creature_names):
                if name in names and row < model.rowCount():
                    selection.select(model.index(row, 0), flags)
        finally:
            self._syncing_selection = False

    def _press_is_in_controls(self, global_pos) -> bool:
        """True while the click is inside the Combat Controls dock."""
        dock = getattr(self, "controls_dock", None)
        if dock is None or not dock.isVisible():
            return False
        return dock.rect().contains(dock.mapFromGlobal(global_pos))

    def focus_creature_filter(self):
        self.controls_dock.show()
        self.creature_filter.setFocus(Qt.ShortcutFocusReason)
        self.creature_filter.selectAll()

    def _build_statblock_dock(self):
        """Right dock: the statblock reader plus its monster picker."""
        self.stat_layout = QVBoxLayout()
        self.stat_layout.setContentsMargins(8, 8, 8, 8)
        self.stat_layout.setSpacing(6)

        self.statblock_widget = StatblockWidget(self)

        self.monster_list = QListWidget(self)
        self.monster_list.setSelectionMode(QListWidget.SingleSelection)
        self.monster_list.itemSelectionChanged.connect(self.update_statblock_image)
        # Height follows the number of monsters (see _fit_monster_list_height).
        # A flat 80–140px box left a picker mostly empty in a one-monster fight
        # and stole that space from the statblock.
        self.monster_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.monster_list.setToolTip("Pick a monster to show its statblock")
        self.monster_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.monster_list.customContextMenuRequested.connect(self._monster_list_context_menu)

        # Statblock fills available space; the picker is pinned underneath it.
        self.stat_layout.addWidget(self.statblock_widget, stretch=1)
        self.stat_layout.addWidget(self.monster_list)
        self._fit_monster_list_height()

        self.stat_widget = QWidget()
        self.stat_widget.setLayout(self.stat_layout)
        self.stat_widget.setMinimumWidth(240)

        self.statblock_dock = QDockWidget("Statblock", self)
        self.statblock_dock.setObjectName("statblockDock")  # required by saveState()
        self.statblock_dock.setWidget(self.stat_widget)
        self.statblock_dock.setMinimumWidth(260)
        self.statblock_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.statblock_dock)

        _screen_w = QApplication.primaryScreen().availableGeometry().width()
        self.resizeDocks(
            [self.controls_dock, self.statblock_dock],
            [250, min(int(_screen_w * 0.28), 460)],
            Qt.Horizontal,
        )

    def _build_status_bar(self):
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.bridge_status_label = QLabel("● Bridge: Disabled")
        self.bridge_status_label.setToolTip("Foundry VTT bridge connection state")
        self.bridge_status_label.setStyleSheet("padding: 0 8px; color: #888;")
        self.status_bar.addPermanentWidget(self.bridge_status_label)

    # ---- layout persistence -------------------------------------------------

    # The saved panel configuration is the source of truth for where things sit.
    # Free-form dock dragging is opt-in; only then is the dragged arrangement
    # remembered instead.

    def _dock_for_key(self, key: str):
        return {
            "controls": getattr(self, "controls_dock", None),
            "statblock": getattr(self, "statblock_dock", None),
        }.get(key)

    def apply_panel_layout(self, config: dict = None):
        """Place every panel according to `config` (defaults to the saved one)."""
        if config is None:
            config = load_panel_layout()
        self._panel_layout = config

        allow_drag = bool(config.get("allow_drag", False))
        docks, widths = [], []

        for key, entry in (config.get("panels") or {}).items():
            dock = self._dock_for_key(key)
            if dock is None:
                continue
            area = (
                Qt.RightDockWidgetArea
                if entry.get("side") == "right"
                else Qt.LeftDockWidgetArea
            )
            if dock.isFloating():
                dock.setFloating(False)
            self.addDockWidget(area, dock)
            dock.setVisible(bool(entry.get("visible", True)))
            # Hidden docks are tracked too, so re-showing one later restores
            # its configured width rather than a Qt default.
            docks.append(dock)
            widths.append(int(entry.get("width", 250)))

        self._pending_dock_widths = (docks, widths)
        watcher = getattr(self, "_dock_watcher", None)
        if watcher is None:
            watcher = self._dock_watcher = _DockResizeWatcher(self)
            for dock in docks:
                dock.installEventFilter(watcher)
        # resizeDocks is only honoured once the widgets have been laid out, so
        # before the window is on screen it silently does nothing. Apply it now
        # for the live case, and again after the next layout pass so the widths
        # survive startup.
        self._apply_dock_widths()
        if docks:
            QTimer.singleShot(0, self._apply_dock_widths)

        toolbar_config = config.get("toolbar") or {}
        toolbar_area = (
            Qt.BottomToolBarArea
            if toolbar_config.get("area") == "bottom"
            else Qt.TopToolBarArea
        )
        self.addToolBar(toolbar_area, self.filetool_bar)
        # An empty toolbar is hidden regardless of the preference.
        self.filetool_bar.setVisible(
            bool(toolbar_config.get("visible", True)) and bool(self.filetool_bar.actions())
        )
        self.apply_toolbar_button_style(toolbar_config.get("button_style"))

        self.set_dragging_allowed(allow_drag)

    def _apply_dock_widths(self):
        """Re-assert the configured dock widths after Qt has laid the window out."""
        pending = getattr(self, "_pending_dock_widths", None)
        if not pending:
            return
        pairs = [(d, w) for d, w in zip(*pending) if d is not None and d.isVisible()]
        if pairs:
            self.resizeDocks([d for d, _ in pairs], [w for _, w in pairs], Qt.Horizontal)

    def _remembered_width(self, dock) -> int:
        """The width a hidden dock should come back at, if we captured one."""
        pending = getattr(self, "_pending_dock_widths", None)
        if not pending:
            return 0
        docks, widths = pending
        return widths[docks.index(dock)] if dock in docks else 0

    def remember_dock_width(self, dock):
        """Record a dock's current width as the one to restore when re-shown."""
        pending = getattr(self, "_pending_dock_widths", None)
        if not pending or dock is None or dock.width() <= 0:
            return
        docks, widths = pending
        if dock in docks:
            widths[docks.index(dock)] = dock.width()
        else:
            docks.append(dock)
            widths.append(dock.width())

    def showEvent(self, event):
        super().showEvent(event)
        # The first show is the first real layout pass; dock widths set before
        # it were discarded, so apply them once the window actually has a size.
        if not getattr(self, "_dock_widths_applied", False):
            self._dock_widths_applied = True
            QTimer.singleShot(0, self._apply_dock_widths)
            # The window manager's maximize arrives some frames after show, and
            # resizing to it is what knocks the panels out of their configured
            # widths. Keep re-asserting them until the window has settled, then
            # hand control back to the user's own separator drags.
            QTimer.singleShot(_LAYOUT_SETTLE_MS, self._settle_layout)

    def _settle_layout(self):
        """End the startup window: from here, a dock's live width is the user's."""
        self._apply_dock_widths()
        self._layout_settled = True

    def _dock_resized(self, dock):
        """A dock changed width on its own — treat it as the user's choice."""
        if not getattr(self, "_layout_settled", False):
            return
        if monotonic() - getattr(self, "_window_resized_at", 0.0) < _WINDOW_RESIZE_GRACE:
            # Fallout from the window resizing, delivered a layout pass or two
            # later. That width is Qt's arithmetic, not a choice — ignoring it
            # is what stops a squeezed panel from becoming the new normal.
            return
        self.remember_dock_width(dock)

    def set_dragging_allowed(self, allowed: bool):
        """Whether panels can be moved/floated/closed with the mouse."""
        self._allow_panel_drag = bool(allowed)
        features = (
            (
                QDockWidget.DockWidgetMovable
                | QDockWidget.DockWidgetFloatable
                | QDockWidget.DockWidgetClosable
            )
            if allowed
            else QDockWidget.NoDockWidgetFeatures
        )
        for key, _label, _side in PANEL_REGISTRY:
            dock = self._dock_for_key(key)
            if dock is not None:
                dock.setFeatures(features)
        self.filetool_bar.setMovable(allowed)
        self.setDockOptions(
            (
                QMainWindow.AnimatedDocks
                | QMainWindow.AllowNestedDocks
                | QMainWindow.AllowTabbedDocks
            )
            if allowed
            else QMainWindow.AnimatedDocks
        )

    def apply_settings_changes(self):
        """Re-apply what a settings save changed, without a relaunch.

        The bridge can swap transport, URL or token live. Storage cannot: the
        backend object is built during construction and half the app holds
        references to it, so that one still needs a restart and says so.
        """
        try:
            self.restart_bridge_sync()
        except Exception as exc:
            self._log(f"[WARN] Could not restart bridge sync: {exc}")

    def open_layout_settings(self):
        from ui.layout_settings_dialog import LayoutSettingsDialog
        LayoutSettingsDialog(self).exec_()

    def open_color_settings(self):
        from ui.color_settings_dialog import ColorSettingsDialog
        ColorSettingsDialog(self).exec_()

    def refresh_theme(self):
        """
        Re-apply everything that bakes in a colour.

        The stylesheet is rebuilt from the live palette, toolbar icons are
        redrawn in the new tint, and the table is repainted so row colours
        follow immediately rather than at the next turn change.
        """
        from ui.theme import get_stylesheet

        app = QApplication.instance()
        if app is not None:
            base = getattr(app, "_base_stylesheet", None)
            if base is None:
                # Capture whatever the theme library installed underneath ours
                # once, so repeated refreshes don't stack copies of our QSS.
                base = app.styleSheet()
                marker = "/* ── Global ──"
                if marker in base:
                    base = base.split(marker)[0]
                app._base_stylesheet = base
            app.setStyleSheet(base + get_stylesheet())

        self._assign_toolbar_icons()
        self.bridge_status_label.setStyleSheet(
            self.bridge_status_label.styleSheet()
        )
        if hasattr(self, "table_model"):
            self.table_model.refresh()
        if hasattr(self, "table"):
            self.table.viewport().update()

    def save_layout(self):
        """
        Persist window geometry, plus whatever the user changed live.

        Panel visibility is toggleable from the View menu, and the dragged
        arrangement matters only when dragging is enabled — capture both so the
        next launch matches what was on screen.
        """
        try:
            app_settings.set(
                "window_geometry",
                bytes(self.saveGeometry().toBase64()).decode("ascii"),
            )
            config = dict(getattr(self, "_panel_layout", None) or load_panel_layout())
            panels = dict(config.get("panels") or {})
            for key, _label, _side in PANEL_REGISTRY:
                dock = self._dock_for_key(key)
                if dock is None:
                    continue
                entry = dict(panels.get(key) or {})
                entry["visible"] = dock.isVisible()
                # The tracked width, not the live one: a window too narrow to
                # honour it squeezes the dock to its minimum, and persisting
                # that would make the squeeze permanent.
                width = self._remembered_width(dock) or dock.width()
                if width > 0:
                    entry["width"] = width
                panels[key] = entry
            config["panels"] = panels
            toolbar = dict(config.get("toolbar") or {})
            toolbar["visible"] = self.filetool_bar.isVisible()
            config["toolbar"] = toolbar
            save_panel_layout(config)

            # Dragged column widths ride along with the layout rather than
            # hitting the disk on every pixel of a header drag.
            app_settings.set(
                "table_column_widths",
                dict(getattr(self, "_user_column_widths", None) or {}),
            )

            if config.get("allow_drag"):
                app_settings.set(
                    "window_state",
                    bytes(self.saveState(LAYOUT_VERSION).toBase64()).decode("ascii"),
                )
        except Exception as exc:
            self._log(f"[WARN] Could not save window layout: {exc}")

    def restore_layout(self) -> bool:
        """Reapply the saved layout. Returns False when there was nothing to restore."""
        restored = False
        try:
            geometry = app_settings.get("window_geometry")
            if geometry:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
                restored = True

            config = load_panel_layout()
            self.apply_panel_layout(config)

            # A freely dragged arrangement is only meaningful while dragging is
            # enabled; otherwise the declarative config above already won.
            state = app_settings.get("window_state")
            if config.get("allow_drag") and state:
                # restoreState() returns False when the saved layout came from an
                # older, incompatible version — fall back to the config.
                if self.restoreState(
                    QByteArray.fromBase64(state.encode("ascii")), LAYOUT_VERSION
                ):
                    restored = True
        except Exception as exc:
            self._log(f"[WARN] Could not restore window layout: {exc}")
            return restored
        return restored

    def reset_layout(self):
        """Put every panel back to the shipped defaults."""
        from ui.layout_settings_dialog import DEFAULT_PANEL_LAYOUT
        from copy import deepcopy

        config = deepcopy(DEFAULT_PANEL_LAYOUT)
        save_panel_layout(config)
        self.apply_panel_layout(config)
        self._user_column_widths = {}
        app_settings.set("table_column_widths", {})
        self.adjust_table_size()
        save_control_sections(list(DEFAULT_CONTROL_SECTIONS))
        self.apply_control_sections()
        toast(self, "Panel layout reset", "success")

    def resizeEvent(self, event):
        width_changed = (
            event.oldSize().width() > 0
            and event.size().width() != event.oldSize().width()
        )
        if width_changed:
            # Stamped before super(), which relays out the docks synchronously
            # and so delivers their resizes while this is the reason for them.
            self._window_resized_at = monotonic()

        super().resizeEvent(event)
        reposition_toasts(self)

        # A panel is a fixed pixel width the user picked; the table absorbs the
        # difference when the window changes size. Left to itself Qt hands the
        # extra width to the docks proportionally, so they drift every session
        # — the window manager's maximize is itself such a resize.
        if width_changed:
            QTimer.singleShot(0, self._apply_dock_widths)

    def notify(self, message: str, level: str = "info"):
        """Transient, in-window feedback. The toast is the part that always
        happens; the status bar echo is opt-in (View -> Status Bar Messages)."""
        self.show_status_message(message)
        toast(self, message, level)

    def show_banner(
        self,
        key: str,
        message: str,
        level: str = "warning",
        action_label: str = None,
        action=None,
        dismissable: bool = True,
    ):
        """
        Raise a persistent notification that stays until the condition clears.

        For anything still true after a toast would have faded — a dead bridge,
        a storage backend that can't be reached.
        """
        self.banner_area.show_banner(
            key, message, level, action_label, action, dismissable
        )

    def clear_banner(self, key: str):
        self.banner_area.clear_banner(key)

    STATUS_MESSAGES_SETTING = "status_messages_enabled"

    def status_messages_enabled(self) -> bool:
        """Off by default: the turn announcement fires on every turn change,
        and what it says is already on screen -- the "Active:" label and the
        highlighted row. Anything genuinely worth interrupting for goes through
        notify(), which raises a toast as well."""
        return bool(app_settings.get(self.STATUS_MESSAGES_SETTING, False))

    def show_status_message(self, msg: str, timeout_ms: int = 4000):
        if not self.status_messages_enabled():
            return
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(msg, timeout_ms)

    def toggle_status_messages(self, enabled: bool):
        app_settings.set(self.STATUS_MESSAGES_SETTING, bool(enabled))
        if not enabled and hasattr(self, "status_bar"):
            # Clear whatever is on screen now; showMessage's own timeout would
            # otherwise leave the last one sitting there after switching off.
            self.status_bar.clearMessage()

    def _populate_groups_menu(self):
        """Rebuild the PC Groups submenu: manager entry + one-click loaders."""
        self.groups_menu.clear()
        new_action = self.groups_menu.addAction("New Group…")
        new_action.triggered.connect(self.new_pc_group)
        manage_action = self.groups_menu.addAction("Manage Groups…")
        manage_action.triggered.connect(self.open_pc_groups)
        self.groups_menu.addSeparator()
        try:
            groups = self.list_pc_groups()
        except Exception:
            groups = []
        if not groups:
            empty = self.groups_menu.addAction("(no saved groups)")
            empty.setEnabled(False)
            return
        for display, key in groups:
            act = self.groups_menu.addAction(display)
            act.triggered.connect(lambda _=False, k=key: self._quick_load_group(k))

    def _quick_load_group(self, key: str):
        try:
            self.load_pc_group(key)
        except Exception as e:
            report_error(self, "Load Group Failed",
                         f"Could not load the PC group '{key}'.", e)
            return
        self.notify(f"Loaded PC group: {self._pc_group_display(key)}", "success")

    def open_pc_groups(self):
        from ui.pc_groups_dialog import PCGroupsDialog
        PCGroupsDialog(self).exec_()

    def ignore_creature_in_foundry_sync(self, name, creature):
        """Ignore this creature by actor id when we know it, else by name."""
        actor_id = getattr(creature, "foundry_actor_id", None)
        if actor_id:
            detail = "Its Foundry actor will be skipped on future snapshots."
        else:
            detail = f"Combatants named '{name}' will be skipped on future snapshots."
        resp = QMessageBox.question(
            self, "Ignore in Foundry Sync",
            f"Stop tracking '{name}'?\n\n{detail}\n"
            "Manage this later under Tools → Foundry Ignore List.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        if actor_id:
            self.add_foundry_ignore(actor_id=str(actor_id))
        else:
            self.add_foundry_ignore(pattern=str(name))
        removed = self.prune_ignored_creatures()
        if name not in removed:
            # No Foundry ids and the name didn't match — remove it directly.
            self.manager.rm_creatures([name])
            self.manager.sort_creatures()
            self.table_model.refresh()
            self.build_turn_order()
            self.update_table()
            self.pop_lists()
        self.notify(f"Ignoring '{name}' in Foundry sync", "info")

    def open_foundry_ignore(self):
        from ui.foundry_ignore_dialog import FoundryIgnoreDialog
        FoundryIgnoreDialog(self).exec_()

    def new_pc_group(self):
        """Straight to the 'name it, then build the roster' flow."""
        from ui.pc_groups_dialog import create_new_pc_group
        create_new_pc_group(self, self)

    BRIDGE_BANNER_KEY = "bridge_disconnected"

    def set_bridge_status(self, state: str) -> None:
        if not hasattr(self, "bridge_status_label"):
            return
        if state == "connected":
            self.bridge_status_label.setText("● Bridge: Connected")
            self.bridge_status_label.setStyleSheet("padding: 0 8px; color: #2ecc71;")
            self.clear_banner(self.BRIDGE_BANNER_KEY)
        elif state == "error":
            self.bridge_status_label.setText("● Bridge: Disconnected")
            self.bridge_status_label.setStyleSheet("padding: 0 8px; color: #e74c3c;")
            # Losing sync silently is the worst case: the app keeps accepting
            # HP and initiative edits that never reach Foundry.
            self.show_banner(
                self.BRIDGE_BANNER_KEY,
                "Foundry bridge disconnected — HP, initiative and condition "
                "changes are not syncing.",
                "error",
                action_label="Show Log",
                action=self.show_log,
            )
        else:
            self.bridge_status_label.setText("● Bridge: Disabled")
            self.bridge_status_label.setStyleSheet("padding: 0 8px; color: #888;")
            self.clear_banner(self.BRIDGE_BANNER_KEY)

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

        self.edit_menu = self.menu_bar.addMenu("&Edit")
        # The player characters and the rosters they belong to are one subject,
        # and neither is a File operation. Sits next to Edit and Encounters,
        # with the rest of what happens at the table.
        self.characters_menu = self.menu_bar.addMenu("&Characters")
        self.encounter_menu = self.menu_bar.addMenu("&Encounters")
        self.monsters_menu = self.menu_bar.addMenu("&Parsers")
        self.tools_menu = self.menu_bar.addMenu("&Tools")
        self.view_menu = self.menu_bar.addMenu("&View")
        self.help_menu = self.menu_bar.addMenu("&Help")

        self.filetool_bar = QToolBar("Toolbar", self)
        self.filetool_bar.setObjectName("mainToolBar")  # required by saveState()
        self.filetool_bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.TopToolBarArea, self.filetool_bar)

        self.save_action = QAction("Save", self)
        self.save_action.triggered.connect(self.save_state)
        self.save_action.setToolTip("Save current state")
        self.file_menu.addAction(self.save_action)

        self.save_as_action = QAction('Save As', self)
        self.save_as_action.triggered.connect(self.save_as_encounter)
        self.save_as_action.setToolTip("Save current encounter as a new file")
        self.file_menu.addAction(self.save_as_action)

        self.file_menu.addSeparator()
        self.settings_action = QAction("Settings…", self)
        self.settings_action.triggered.connect(self.open_settings)
        self.file_menu.addAction(self.settings_action)

        # Built here, but added to View only (_setup_view_menu). They used to
        # sit in both menus; View is where the other customizers are, and where
        # anyone looks for them.
        self.customize_layout_action = QAction("Customize Layout…", self)
        self.customize_layout_action.setToolTip(
            "Choose where each panel sits, how wide it is, and where the toolbar goes"
        )
        self.customize_layout_action.triggered.connect(self.open_layout_settings)

        self.customize_toolbar_action = QAction("Customize Toolbar…", self)
        self.customize_toolbar_action.triggered.connect(self.open_customize_toolbar)

        self.customize_colors_action = QAction("Customize Colors…", self)
        self.customize_colors_action.setToolTip(
            "Change the turn, bloodied, down and dead row colours, and the theme"
        )
        self.customize_colors_action.triggered.connect(self.open_color_settings)

        # "Initialize" puts the active PC group into the initiative order, so it
        # belongs with the characters rather than with the turn/combatant edits.
        self.initialize_players_action = QAction("Initialize Players", self)
        self.initialize_players_action.setToolTip(
            "Put the active PC group into the initiative order"
        )
        self.initialize_players_action.triggered.connect(self.init_players)

        self.load_enc_button = QAction("Load Encounter", self)
        self.load_enc_button.triggered.connect(self.load_encounter)
        self.load_enc_button.setToolTip("Load a saved encounter")
        self.encounter_menu.addAction(self.load_enc_button)

        self.add_button = QAction("Add Combatant", self)
        self.add_button.triggered.connect(self.add_combatant)
        self.add_button.setToolTip("Add new combatants to the encounter")
        self.edit_menu.addAction(self.add_button)

        self.rmv_button = QAction("Remove Combatants", self)
        self.rmv_button.triggered.connect(self.remove_combatant)
        self.rmv_button.setToolTip("Remove combatants from the encounter")
        self.edit_menu.addAction(self.rmv_button)

        self.build_encounter = QAction("Build Encounter", self)
        self.build_encounter.triggered.connect(self.save_encounter)
        self.encounter_menu.addAction(self.build_encounter)

        self.merge_encounters = QAction('Merge Encounters', self)
        self.merge_encounters.triggered.connect(self.merge_encounter)
        self.merge_encounters.setToolTip("Merge another encounter into the current one")
        self.encounter_menu.addAction(self.merge_encounters)

        self.add_lair_action_button = QAction("Add Lair Action", self)
        self.add_lair_action_button.triggered.connect(self.add_lair_action_combatant)
        self.encounter_menu.addAction(self.add_lair_action_button)

        self.active_encounters = QAction("Activate/Deactivate Encounters", self)
        self.active_encounters.triggered.connect(self.manage_encounter_statuses)
        self.encounter_menu.addAction(self.active_encounters)

        self.delete_encounters_button = QAction("Delete Encounter", self)
        self.delete_encounters_button.triggered.connect(self.delete_encounters)
        self.encounter_menu.addAction(self.delete_encounters_button)

        self.update_characters_action = QAction("Create/Update Characters…", self)
        self.update_characters_action.triggered.connect(self.create_or_update_characters)
        self.characters_menu.addAction(self.update_characters_action)
        self.characters_menu.addAction(self.initialize_players_action)

        self.characters_menu.addSeparator()

        # PC Groups: quick-switch saved player rosters. The submenu is rebuilt
        # each time it opens so newly saved groups appear without a restart.
        # Added here, after the editor, so the menu reads editor-then-rosters.
        self.groups_menu = self.characters_menu.addMenu("PC Groups")
        self.groups_menu.aboutToShow.connect(self._populate_groups_menu)

        self.import_statblock_action = QAction("Import Statblock...", self)
        self.import_statblock_action.triggered.connect(self.open_import_statblock_dialog)
        self.monsters_menu.addAction(self.import_statblock_action)

        self.import_spell_action = QAction("Import Spell...", self)
        self.import_spell_action.triggered.connect(self.open_import_spell_dialog)
        self.monsters_menu.addAction(self.import_spell_action)

        self.bulk_import_items_action = QAction("Bulk Import Items...", self)
        self.bulk_import_items_action.triggered.connect(self.open_bulk_item_import_dialog)
        self.monsters_menu.addAction(self.bulk_import_items_action)

        self.monsters_menu.addSeparator()
        self.lookup_action = QAction("Reference Lookup", self)
        self.lookup_action.setToolTip("Look up spells, monsters, and conditions")
        self.lookup_action.triggered.connect(self.open_lookup_dialog)
        self.monsters_menu.addAction(self.lookup_action)

        self.shop_generator_action = QAction("Shop Generator…", self)
        self.shop_generator_action.triggered.connect(self.open_shop_generator_dialog)
        self.tools_menu.addAction(self.shop_generator_action)

        self.foundry_ignore_action = QAction("Foundry Ignore List…", self)
        self.foundry_ignore_action.setToolTip(
            "Keep summons, familiars and effect tokens out of initiative"
        )
        self.foundry_ignore_action.triggered.connect(self.open_foundry_ignore)
        self.tools_menu.addAction(self.foundry_ignore_action)

        self.next_turn_action = QAction("Next Turn", self)
        self.next_turn_action.triggered.connect(self.next_turn)
        self.edit_menu.addAction(self.next_turn_action)

        self.prev_turn_action = QAction("Previous Turn", self)
        self.prev_turn_action.triggered.connect(self.prev_turn)
        self.edit_menu.addAction(self.prev_turn_action)

        self._setup_view_menu()
        self._setup_help_menu()

        # Build the id → QAction map used by _apply_toolbar_config.
        # Keys must match the ids in ui.toolbar_customize_dialog.TOOLBAR_REGISTRY.
        self._toolbar_action_map: dict[str, QAction] = {
            "save":                 self.save_action,
            "save_as":              self.save_as_action,
            "add_combatant":        self.add_button,
            "remove_combatants":    self.rmv_button,
            "load_encounter":       self.load_enc_button,
            "build_encounter":      self.build_encounter,
            "merge_encounters":     self.merge_encounters,
            "add_lair_action":      self.add_lair_action_button,
            "reference_lookup":     self.lookup_action,
            "initialize":           self.initialize_players_action,
            "next_turn":            self.next_turn_action,
            "prev_turn":            self.prev_turn_action,
            "activate_encounters":  self.active_encounters,
            "delete_encounter":     self.delete_encounters_button,
            "update_characters":    self.update_characters_action,
            "import_statblock":     self.import_statblock_action,
            "import_spell":         self.import_spell_action,
            "bulk_import_items":    self.bulk_import_items_action,
            "shop_generator":       self.shop_generator_action,
            "settings":             self.settings_action,
            "foundry_ignore":       self.foundry_ignore_action,
            "show_log":             self.show_log_action,
        }

        self._assign_toolbar_icons()

        # Populate toolbar from saved config (or defaults)
        self._apply_toolbar_config()

        # Right-click on toolbar opens customize dialog
        self.filetool_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.filetool_bar.customContextMenuRequested.connect(self._toolbar_context_menu)

    def _assign_toolbar_icons(self):
        """
        Give toolbar actions an icon drawn from the current palette.

        Actions without an honest visual metaphor deliberately get none — a
        wrong icon costs more than a text-only button. See ui.icons.
        """
        tint = colors.TEXT_PRIMARY
        for action_id, action in self._toolbar_action_map.items():
            icon = icon_for(action_id, tint)
            action.setIcon(icon)

    def apply_toolbar_button_style(self, style: str = None):
        """Text-only, icons-only, or both — the user's call."""
        if style is None:
            style = load_panel_layout().get("toolbar", {}).get("button_style", "text_beside_icon")
        self.filetool_bar.setToolButtonStyle(
            {
                "text_only": Qt.ToolButtonTextOnly,
                "icon_only": Qt.ToolButtonIconOnly,
                "text_under_icon": Qt.ToolButtonTextUnderIcon,
            }.get(style, Qt.ToolButtonTextBesideIcon)
        )

    def _setup_view_menu(self):
        """Panel visibility and layout controls, all in one predictable place."""
        # toggleViewAction() keeps the checkmark in sync when the user closes a
        # dock with its own × button, so the menu can never lie about state.
        self.view_menu.addAction(self.controls_dock.toggleViewAction())
        self.view_menu.addAction(self.statblock_dock.toggleViewAction())

        self.toggle_toolbar_action = self.filetool_bar.toggleViewAction()
        self.toggle_toolbar_action.setText("Toolbar")
        self.view_menu.addAction(self.toggle_toolbar_action)

        self.status_messages_action = QAction("Status Bar Messages", self)
        self.status_messages_action.setCheckable(True)
        self.status_messages_action.setChecked(self.status_messages_enabled())
        self.status_messages_action.setToolTip(
            "Echo actions as text in the bottom-left corner"
        )
        self.status_messages_action.toggled.connect(self.toggle_status_messages)
        self.view_menu.addAction(self.status_messages_action)

        self.view_menu.addSeparator()

        # Placement and sizing live in a dialog rather than being dragged, so
        # the layout can't be knocked out of shape by a stray mouse gesture.
        self.view_menu.addAction(self.customize_layout_action)
        self.view_menu.addAction(self.customize_toolbar_action)
        self.view_menu.addAction(self.customize_colors_action)

        self.customize_controls_action = QAction("Customize Combat Controls…", self)
        self.customize_controls_action.setToolTip(
            "Show, hide and reorder the sections of the Combat Controls panel"
        )
        self.customize_controls_action.triggered.connect(self.open_control_sections)
        self.view_menu.addAction(self.customize_controls_action)

        self.customize_shortcuts_action = QAction("Customize Shortcuts…", self)
        self.customize_shortcuts_action.setToolTip("Rebind the keyboard shortcuts")
        self.customize_shortcuts_action.triggered.connect(self.open_shortcut_settings)
        self.view_menu.addAction(self.customize_shortcuts_action)

        self.reset_columns_action = QAction("Reset Column Widths", self)
        self.reset_columns_action.setToolTip(
            "Size the initiative table's columns from their contents again"
        )
        self.reset_columns_action.triggered.connect(self.reset_column_widths)
        self.view_menu.addAction(self.reset_columns_action)

        self.reset_layout_action = QAction("Reset Panel Layout", self)
        self.reset_layout_action.setToolTip("Put every panel back to its default position")
        self.reset_layout_action.triggered.connect(self.reset_layout)
        self.view_menu.addAction(self.reset_layout_action)

    def _setup_help_menu(self):
        self.shortcuts_action = QAction("Keyboard Shortcuts", self)
        self.shortcuts_action.triggered.connect(self.show_shortcuts)
        self.help_menu.addAction(self.shortcuts_action)

        self.show_log_action = QAction("Show Log…", self)
        self.show_log_action.setToolTip("Recent activity and errors — useful when reporting a bug")
        self.show_log_action.triggered.connect(self.show_log)
        self.help_menu.addAction(self.show_log_action)

        self.release_notes_action = QAction("Release Notes…", self)
        self.release_notes_action.setToolTip("What changed in each version")
        self.release_notes_action.triggered.connect(self.show_release_notes)
        self.help_menu.addAction(self.release_notes_action)

        self.versions_action = QAction("Installed Versions…", self)
        self.versions_action.setToolTip(
            "Switch between the versions installed side by side, or remove one"
        )
        self.versions_action.triggered.connect(self.open_versions_dialog)
        self.help_menu.addAction(self.versions_action)

        self.check_updates_action = QAction("Check for Updates…", self)
        self.check_updates_action.setToolTip(
            "Ask GitHub whether a newer version has been released"
        )
        self.check_updates_action.triggered.connect(self.check_for_updates_now)
        self.help_menu.addAction(self.check_updates_action)

        self.help_menu.addSeparator()

        # Carries the CC-BY-4.0 notice for the bundled SRD library, which has
        # to accompany the material in the distributed app, not just the repo.
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self.show_about)
        self.help_menu.addAction(self.about_action)

    def show_release_notes(self, version=None):
        from ui.release_notes_dialog import ReleaseNotesDialog
        ReleaseNotesDialog(self, version=version or None).exec_()

    def show_about(self):
        from ui.about_dialog import AboutDialog
        AboutDialog(self).exec_()

    def show_log(self):
        from ui.log_dialog import LogDialog
        LogDialog(self).exec_()

    def _shortcut_targets(self) -> dict:
        """Registry id → the QAction or QShortcut it drives.

        Ids must match SHORTCUT_SCHEMA in shortcut_settings_dialog.py, the same
        contract _toolbar_action_map has with TOOLBAR_REGISTRY.
        """
        candidates = {
            "next_turn":            getattr(self, "next_turn_action", None),
            "prev_turn":            getattr(self, "prev_turn_action", None),
            "save_state":           getattr(self, "save_action", None),
            "reference_lookup":     getattr(self, "lookup_action", None),
            "show_shortcuts":       getattr(self, "shortcuts_action", None),
            "focus_filter":         getattr(self, "filter_shortcut", None),
            "statblock_zoom_in":    getattr(self, "zoom_in_shortcut", None),
            "statblock_zoom_out":   getattr(self, "zoom_out_shortcut", None),
            "statblock_zoom_reset": getattr(self, "zoom_reset_shortcut", None),
        }
        return {key: target for key, target in candidates.items() if target is not None}

    def apply_shortcuts(self):
        """Bind every registered shortcut from settings. Safe to call again.

        Called once at startup and again whenever the customizer saves, so a
        rebind takes effect immediately rather than at the next launch.
        """
        bindings = load_shortcuts()

        for key, target in self._shortcut_targets().items():
            sequence = QKeySequence(bindings.get(key, ""))
            # QShortcut and QAction spell the same idea differently.
            if isinstance(target, QShortcut):
                target.setKey(sequence)
            else:
                target.setShortcut(sequence)

        # The unshifted twin of Ctrl++ only makes sense while zoom-in still is
        # Ctrl++; once rebound, an alias nobody chose would just be a mystery.
        alias = getattr(self, "zoom_in_alias_shortcut", None)
        if alias is not None:
            at_default = (
                bindings.get("statblock_zoom_in")
                == shortcut_defaults()["statblock_zoom_in"]
            )
            alias.setKey(QKeySequence(ZOOM_IN_ALIAS if at_default else ""))

        self._refresh_shortcut_hints(bindings)

    def _refresh_shortcut_hints(self, bindings: dict):
        """Keep the hints that quote a shortcut honest after a rebind."""
        def hint(key: str) -> str:
            sequence = QKeySequence(bindings.get(key, "")).toString(
                QKeySequence.NativeText
            )
            return f" ({sequence})" if sequence else ""

        if hasattr(self, "prev_button"):
            self.prev_button.setToolTip(f"Go to previous turn{hint('prev_turn')}")
        if hasattr(self, "next_button"):
            self.next_button.setToolTip(f"Advance to next turn{hint('next_turn')}")
        if hasattr(self, "creature_filter"):
            self.creature_filter.setPlaceholderText(
                f"Filter combatants…{hint('focus_filter')}"
            )

    def open_shortcut_settings(self):
        ShortcutSettingsDialog(self).exec_()

    RESTART_BANNER_KEY = "restart-required"

    def restart_app(self) -> bool:
        """Save, start a fresh copy, and quit. Returns False if it couldn't.

        Three shapes of installation, in decreasing order of how well this
        works: a versioned install restarts through the launcher, which waits
        for this process to exit first; a flat frozen build re-runs its own
        executable; a source checkout re-runs the interpreter. Only the first
        can guarantee the old process is gone before the new one opens the same
        files, so the others save first and skip the save on the way out.
        """
        from app import install_layout, update_install

        for step in ("save_state", "save_layout"):
            try:
                getattr(self, step)()
            except Exception as exc:
                self._log(f"[WARN] Could not {step} before restart: {exc}")
        # closeEvent must not save again: the replacement may already have
        # started and written its own state by then.
        self._restarting = True

        try:
            layout = install_layout.detect()
            if layout is not None and layout.has_launcher():
                update_install.relaunch(layout)
            else:
                command = (
                    [sys.executable] + sys.argv[1:]
                    if install_layout.running_frozen()
                    else [sys.executable] + sys.argv
                )
                kwargs = {"close_fds": True}
                if os.name == "posix":
                    kwargs["start_new_session"] = True
                subprocess.Popen(command, **kwargs)
        except Exception as exc:
            self._restarting = False
            report_error(
                self, "Could Not Restart",
                "The settings are saved, but the app could not restart itself. "
                "Close and reopen it to pick them up.",
                exc,
            )
            return False

        QApplication.instance().quit()
        return True

    def prompt_restart(self, what: str = "Some settings") -> None:
        """Offer to restart now, rather than leaving the user to do it by hand.

        Declining leaves a banner with the same button, so the offer is still
        one click away once they have finished what they were doing.
        """
        answer = QMessageBox.question(
            self,
            "Restart Required",
            f"{what} only take effect when the app restarts.\n\n"
            "Restart now? Your combat is saved first.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.restart_app()
            return
        self.show_banner(
            self.RESTART_BANNER_KEY,
            f"{what} take effect after a restart.",
            level="info",
            action_label="Restart Now",
            action=self.restart_app,
        )

    def apply_synced_settings(self):
        """Re-read everything a pull may have changed, without a restart.

        Window geometry is deliberately not synced, so nothing here has to
        touch the window itself.
        """
        try:
            colors.apply(colors.load())
            self.refresh_theme()
            self.apply_shortcuts()
            self.apply_control_sections()
            self._apply_toolbar_config()
            self.apply_panel_layout(load_panel_layout())
            self._user_column_widths = dict(
                app_settings.get("table_column_widths") or {}
            )
            self.adjust_table_size()
            toast(self, "Settings pulled from your other machine", "success")
        except Exception as exc:
            report_error(
                self, "Could Not Apply Settings",
                "The settings were pulled, but applying them live failed. "
                "Restarting the app will pick them up.",
                exc,
            )

    # Checked periodically, not once: an update's probation usually expires
    # while the app is still running, and nobody restarts just to reclaim disk.
    _RETIREMENT_CHECK_MS = 5 * 60 * 1000

    # One check per tick, slowly. The app has to stay usable while a build is
    # being vetted -- someone may be mid-combat, and none of this is urgent.
    _SELF_TEST_TICK_MS = 400
    SELF_TEST_BANNER_KEY = "self-test-failed"

    def verify_new_version(self):
        """Run the self-test once, after an update, and act on the result.

        Passing retires the version this one replaced immediately -- the point
        of testing is to answer that question with evidence rather than by
        waiting out a timer. Failing leaves it exactly where it is and offers
        to go back to it.
        """
        from app import install_layout, self_test

        layout = install_layout.detect()
        if layout is None:
            return                                  # nothing to fall back to
        if app_settings.get(self.VERIFIED_KEY) == layout.version:
            return                                  # already vetted this build

        self._self_test_layout = layout
        self._self_test_queue = list(self_test.all_checks())
        self._self_test_results = []
        self._log(f"[SelfTest] Checking {layout.version} after update")

        self._self_test_timer = QTimer(self)
        self._self_test_timer.timeout.connect(self._run_next_check)
        self._self_test_timer.start(self._SELF_TEST_TICK_MS)

    VERIFIED_KEY = "verified_version"

    def _run_next_check(self):
        from app import self_test

        if not self._self_test_queue:
            self._self_test_timer.stop()
            self._finish_self_test()
            return
        check = self._self_test_queue.pop(0)
        result = self_test.run_check(check)
        self._self_test_results.append(result)
        if result.failed:
            self._log(f"[SelfTest] FAILED {result.label}: {result.detail}")

    def _finish_self_test(self):
        from app import install_layout, self_test

        layout = self._self_test_layout
        results = self._self_test_results
        summary = self_test.summarise(results)
        failure = self_test.first_failure(results)

        if failure is None:
            self._log(f"[SelfTest] {layout.version} passed ({summary})")
            app_settings.set(self.VERIFIED_KEY, layout.version)
            # Vetted, so the build it replaced has done its job.
            self._retire_superseded_now(layout)
            return

        self._log(f"[SelfTest] {layout.version} failed ({summary})")
        previous = self._previous_version(layout)
        if previous is None:
            self.show_banner(
                self.SELF_TEST_BANNER_KEY,
                f"This version failed a self-check after updating — "
                f"{failure.label}: {failure.detail}. No earlier version is "
                f"installed to go back to.",
                level="error",
            )
            return

        self.show_banner(
            self.SELF_TEST_BANNER_KEY,
            f"Version {layout.version} failed a self-check after updating — "
            f"{failure.label}. Your data is untouched, and {previous} is still "
            f"installed.",
            level="error",
            action_label=f"Go Back to {previous}",
            action=lambda: self._revert_to(layout, previous),
        )

    def _previous_version(self, layout):
        """The newest installed version that isn't the one running."""
        from app.update_check import _parse

        others = [v for v in layout.installed_versions() if v != layout.version]
        if not others:
            return None
        return sorted(others, key=_parse, reverse=True)[0]

    def _revert_to(self, layout, version: str):
        from app import install_layout

        try:
            install_layout.write_current(layout, version)
            install_layout.cancel_retirement(version)
            # Don't let the failing build be re-vetted and re-blessed on the
            # way past; it has already been judged.
            app_settings.set(self.VERIFIED_KEY, "")
        except Exception as exc:
            report_error(self, "Could Not Switch Version",
                         f"Could not select {version} to run next.", exc)
            return
        self.clear_banner(self.SELF_TEST_BANNER_KEY)
        self.restart_app()

    def _retire_superseded_now(self, layout):
        """Drop the grace period for versions this build has superseded."""
        from app import install_layout
        from app.update_install import prune_versions

        try:
            keep = install_layout.keep_versions()
            removed = prune_versions(layout, keep=keep)
            for version in removed:
                install_layout.cancel_retirement(version)
            if removed:
                self._log(
                    f"[SelfTest] {layout.version} verified; removed {', '.join(removed)}"
                )
        except Exception as exc:
            self._log(f"[WARN] Could not retire superseded versions: {exc}")

    def start_version_housekeeping(self):
        """Retire superseded versions once their probation is up."""
        from app.install_layout import detect

        if detect() is None:
            return          # source checkout or a flat install: nothing to prune
        self._retirement_timer = QTimer(self)
        self._retirement_timer.timeout.connect(self._retire_old_versions)
        self._retirement_timer.start(self._RETIREMENT_CHECK_MS)

    def _retire_old_versions(self):
        from app.install_layout import prune_with_grace

        try:
            removed, _waiting = prune_with_grace()
        except Exception as exc:
            self._log(f"[WARN] Could not retire old versions: {exc}")
            return
        if removed:
            self._log(f"[Update] Removed old versions: {', '.join(removed)}")

    def open_versions_dialog(self):
        from ui.versions_dialog import VersionsDialog
        VersionsDialog(self).exec_()

    def open_control_sections(self):
        ControlSectionsDialog(self).exec_()

    def show_shortcuts(self):
        """A discoverable list of shortcuts — otherwise they're only in tooltips.

        Read from the live bindings, so a rebind shows up here instead of this
        list quietly becoming a list of what the shortcuts used to be.
        """
        bindings = load_shortcuts()
        lines = []
        for group_name, entries in SHORTCUT_SCHEMA:
            lines.append(group_name.upper())
            for key, label, _default, _tip in entries:
                sequence = QKeySequence(bindings.get(key, "")).toString(
                    QKeySequence.NativeText
                )
                lines.append(f"  {sequence or '— unbound —':<16}{label}")
            lines.append("")

        lines.append("FIXED")
        for sequence, label in FIXED_SHORTCUTS:
            lines.append(f"  {sequence:<16}{label}")

        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard Shortcuts")
        layout = QVBoxLayout(dialog)
        view = QTextEdit(dialog)
        view.setReadOnly(True)
        # Monospaced, or the two columns won't line up.
        view.setFont(QFont("monospace"))
        view.setPlainText("\n".join(lines))
        view.setMinimumSize(430, 380)
        layout.addWidget(view)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, dialog)
        customize = buttons.addButton("Customize…", QDialogButtonBox.ActionRole)
        # Reopened afterwards so the list shows what was just changed.
        def _customize():
            dialog.accept()
            self.open_shortcut_settings()
            self.show_shortcuts()
        customize.clicked.connect(_customize)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec_()

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

        # ❌ Do nothing if it's the virtual spellbook or abilities column
        if attr in ("_spellbook", "_abilities"):
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
        if attr == "_abilities":
            self.show_ability_uses_dropdown(creature, index)
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

    def _commit_hp_overrides(self, creature, temp_hp: int, max_hp_bonus: int) -> None:
        """Apply temp HP and max HP bonus, cap curr_hp, and sync to Foundry."""
        old_temp = int(getattr(creature, "temp_hp", 0) or 0)
        old_bonus = int(getattr(creature, "max_hp_bonus", 0) or 0)

        creature.temp_hp = temp_hp
        creature.max_hp_bonus = max_hp_bonus

        max_total = int(getattr(creature, "effective_max_hp", 0) or 0)
        creature.curr_hp = min(int(getattr(creature, "curr_hp", 0) or 0), max_total)

        name = getattr(creature, "name", "")
        if temp_hp != old_temp:
            self._enqueue_bridge_set_temp_hp(name, temp_hp)
        if max_hp_bonus != old_bonus:
            self._enqueue_bridge_set_max_hp_bonus(name, max_hp_bonus)
            self._enqueue_bridge_set_hp(name, creature.curr_hp)

        self.update_table()

    def _make_hp_editor_widget_action(self, menu: QMenu, creature) -> QWidgetAction:
        """Inline Temp HP / Max HP Bonus editor embedded in a QMenu."""
        container = QWidget()
        layout = QFormLayout(container)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        temp_spin = QSpinBox()
        temp_spin.setRange(0, 9999)
        temp_spin.setValue(int(getattr(creature, "temp_hp", 0) or 0))
        temp_spin.setFixedWidth(90)

        bonus_spin = QSpinBox()
        bonus_spin.setRange(-9999, 9999)
        bonus_spin.setValue(int(getattr(creature, "max_hp_bonus", 0) or 0))
        bonus_spin.setFixedWidth(90)

        layout.addRow("Temp HP:", temp_spin)
        layout.addRow("Max HP Bonus:", bonus_spin)

        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 4, 0, 0)
        apply_btn = QPushButton("Apply")
        clear_btn = QPushButton("Clear")
        btn_layout.addWidget(apply_btn)
        btn_layout.addWidget(clear_btn)
        layout.addRow(btn_row)

        def _apply():
            self._commit_hp_overrides(creature, temp_spin.value(), bonus_spin.value())
            menu.close()

        def _clear():
            self._commit_hp_overrides(creature, 0, 0)
            menu.close()

        apply_btn.clicked.connect(_apply)
        clear_btn.clicked.connect(_clear)
        temp_spin.editingFinished.connect(_apply)
        bonus_spin.editingFinished.connect(_apply)

        action = QWidgetAction(menu)
        action.setDefaultWidget(container)
        return action

    def _make_hp_delta_widget_action(self, menu: QMenu, creature) -> QWidgetAction:
        """Damage/heal entry for one creature, embedded in a QMenu."""
        name = getattr(creature, "name", "")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)

        current = int(getattr(creature, "curr_hp", 0) or 0)
        maximum = int(getattr(creature, "effective_max_hp", 0) or 0)
        heading = QLabel(f"{name} — {current}/{maximum}" if maximum > 0 else name)
        heading.setObjectName("combatInfoLabel")
        layout.addWidget(heading)

        value = QLineEdit()
        value.setValidator(QIntValidator(0, 9999, value))
        value.setPlaceholderText("Amount…")
        value.setFixedWidth(150)
        layout.addWidget(value)

        # Heal first, so the destructive button isn't the one under the cursor
        # after typing -- same ordering as the dock's HP controls.
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        heal_btn = QPushButton("Heal")
        heal_btn.setObjectName("healButton")
        damage_btn = QPushButton("Damage")
        damage_btn.setObjectName("damageButton")
        buttons.addWidget(heal_btn)
        buttons.addWidget(damage_btn)
        layout.addLayout(buttons)

        hint = QLabel("Enter to damage · Shift+Enter to heal")
        # Attribute access, so a user's palette change is picked up (colors.py).
        hint.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 10px;")
        layout.addWidget(hint)

        def _apply(positive: bool):
            text = value.text().strip()
            try:
                amount = int(text)
            except ValueError:
                # The validator keeps this out of reach; belt and braces, since
                # an exception here would surface as a traceback dialog.
                return
            menu.close()
            self.apply_hp_delta(name, amount, positive)
            self.update_table()
            verb = "Healed" if positive else "Damaged"
            self.show_status_message(f"{verb} {name} by {text}")

        heal_btn.clicked.connect(lambda: _apply(True))
        damage_btn.clicked.connect(lambda: _apply(False))
        # returnPressed doesn't report modifiers, so the shift state is read
        # from the keyboard at the moment the key lands.
        value.returnPressed.connect(
            lambda: _apply(bool(QApplication.keyboardModifiers() & Qt.ShiftModifier))
        )

        QTimer.singleShot(0, value.setFocus)

        action = QWidgetAction(menu)
        action.setDefaultWidget(container)
        return action

    def show_hp_dropdown(self, creature, index):
        """Clicking an HP cell asks for damage first -- the common case.

        Temp HP and Max HP Bonus are still here, below the separator, but they
        are the rare edit and no longer the only thing this popup offered.
        """
        menu = QMenu(self)
        menu.addAction(self._make_hp_delta_widget_action(menu, creature))
        menu.addSeparator()
        menu.addAction(self._make_hp_editor_widget_action(menu, creature))
        pos = self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft())
        menu.exec_(pos)


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
                self._clear_statblock()
        else:
            self._clear_statblock()

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

        if getattr(creature, "_type", None) != CreatureType.PLAYER:
            statblock_action = menu.addAction("Set Statblock...")
        else:
            statblock_action = None

        menu.addSeparator()
        menu.addAction(self._make_hp_editor_widget_action(menu, creature))
        menu.addSeparator()

        edit_public_action = menu.addAction("Edit Public Notes...")
        edit_private_action = menu.addAction("Edit Private Notes...")
        menu.addSeparator()
        clear_conditions_action = menu.addAction("Clear Conditions")
        set_active_action = menu.addAction("Set as Active Turn")
        remove_action = menu.addAction("Remove Combatant")
        ignore_action = menu.addAction("Ignore in Foundry Sync")
        ignore_action.setToolTip(
            "Remove now and keep this out of initiative on future snapshots"
        )

        chosen = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == ignore_action:
            self.ignore_creature_in_foundry_sync(name, creature)
            return

        if statblock_action and chosen == statblock_action:
            try:
                keys = self.storage_api.list_statblock_keys()
            except Exception:
                keys = []
            display_names = sorted(
                k.removesuffix(".json").replace("_", " ").title() for k in keys
            )

            dlg = QDialog(self)
            dlg.setWindowTitle("Set Statblock")
            dlg.setMinimumWidth(300)
            dlg_layout = QVBoxLayout(dlg)

            search_box = QLineEdit()
            search_box.setPlaceholderText("Filter statblocks...")
            picker_list = QListWidget()
            picker_list.addItems(display_names)

            current_override = getattr(creature, "statblock_override", "") or ""
            for i in range(picker_list.count()):
                if picker_list.item(i).text().lower() == current_override.lower():
                    picker_list.setCurrentRow(i)
                    break

            def _filter_picker(text):
                for i in range(picker_list.count()):
                    picker_list.item(i).setHidden(text.lower() not in picker_list.item(i).text().lower())

            search_box.textChanged.connect(_filter_picker)
            picker_list.itemDoubleClicked.connect(dlg.accept)

            dlg_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            dlg_btns.accepted.connect(dlg.accept)
            dlg_btns.rejected.connect(dlg.reject)

            dlg_layout.addWidget(search_box)
            dlg_layout.addWidget(picker_list)
            dlg_layout.addWidget(dlg_btns)

            if dlg.exec_() == QDialog.Accepted:
                item = picker_list.currentItem()
                new_val = (item.text() if item and not item.isHidden() else search_box.text()).strip()
                if new_val:
                    creature.statblock_override = new_val
                    if hasattr(self, "apply_statblock_slots"):
                        self.apply_statblock_slots(creature, creature.statblock_override)
                    self.update_table()
                    self.save_state()
            return

        if chosen == edit_public_action:
            updated = self._show_notes_editor("Edit Public Notes", getattr(creature, "public_notes", "") or "")
            if updated is not None:
                creature.public_notes = updated
                self.table_model.refresh()
                self.update_table()
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

    def show_ability_uses_dropdown(self, creature, index):
        if hasattr(self, "_active_ability_dropdown") and self._active_ability_dropdown:
            self._active_ability_dropdown.close()

        dropdown = AbilityUsesDropdown(creature, self)
        self._active_ability_dropdown = dropdown

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
        # A restart already saved, and its replacement may have written its own
        # state by now -- saving again here would overwrite the newer copy.
        if not getattr(self, "_restarting", False):
            self.save_layout()
        # Commands are delivered on a worker thread now, so a turn change or a
        # damage roll made just before quitting may still be in flight. Time-
        # boxed: a slow bridge must not hold the window open.
        bridge_client = getattr(self, "bridge_client", None)
        if bridge_client is not None and hasattr(bridge_client, "flush_commands"):
            try:
                bridge_client.flush_commands(timeout=2.0)
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

    def _on_column_resized(self, column: int, _old: int, new: int):
        """Record a width the *user* dragged so auto-sizing stops overriding it.

        Without this every update_table() would snap the column back, which is
        what made the header feel unresizable.
        """
        if getattr(self, "_sizing_columns", False) or new <= 0:
            return
        fields = getattr(getattr(self, "table_model", None), "fields", []) or []
        if column < 0 or column >= len(fields):
            return
        self._user_column_widths[fields[column]] = new
        # Narrowing a column takes the table's right edge with it rather than
        # leaving empty body behind -- and can retire the horizontal scrollbar,
        # which is part of the height, so re-fit both directions.
        self.refit_table()

    def reset_column_widths(self):
        """Forget dragged widths and size every column from its contents again."""
        self._user_column_widths = {}
        app_settings.set("table_column_widths", {})
        self.adjust_table_size()
        toast(self, "Column widths reset", "success")

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if (
            hasattr(self, "creature_list")
            and obj is self.creature_list.viewport()
            and event.type() == QEvent.MouseButtonPress
        ):
            return self._list_shift_click(event)

        if hasattr(self, "table") and obj is getattr(self, "central_widget", None):
            if event.type() == QEvent.Resize:
                self.refit_table()
            return False

        if hasattr(self, "table") and obj is self.table.viewport():
            if event.type() == QEvent.Resize:
                self.refit_table()
            return False

        if hasattr(self, "value_input") and obj is self.value_input:
            if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    self.heal_selected_creatures()
                else:
                    self.damage_selected_creatures()
                return True

        if event.type() == event.MouseButtonPress:
            # If the click target is NOT inside the table, clear selection --
            # but not when it lands in the Combat Controls, which are what the
            # selection is *for*: clicking Damage must not drop the targets.
            if hasattr(self, "table"):
                table_rect = self.table.rect()
                table_pos = self.table.mapFromGlobal(event.globalPos())

                if not table_rect.contains(table_pos) and not self._press_is_in_controls(
                    event.globalPos()
                ):
                    # Flagged so the mirror knows this clear wasn't the user
                    # deselecting rows, and leaves the combatant list alone.
                    self._clearing_table_selection = True
                    try:
                        self.table.clearSelection()
                        self.table.setCurrentIndex(self.table.model().index(-1, -1))
                    finally:
                        self._clearing_table_selection = False

        return super().eventFilter(obj, event)
