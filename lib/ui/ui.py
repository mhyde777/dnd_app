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
from PyQt5.QtCore import Qt, QByteArray, QEvent, QObject, QTimer
from PyQt5.QtGui import QKeySequence
from app.app import Application
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
from ui.notifications import report_error, reposition_toasts, toast
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
        self.start_bridge_polling()

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

        self.filter_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.filter_shortcut.activated.connect(self.focus_creature_filter)

        # Statblock legibility without resizing the panel.
        for sequence, slot in (
            ("Ctrl++", self.statblock_widget.zoom_in),
            ("Ctrl+=", self.statblock_widget.zoom_in),   # same physical key, unshifted
            ("Ctrl+-", self.statblock_widget.zoom_out),
            ("Ctrl+0", self.statblock_widget.reset_zoom),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)

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
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.table.setMouseTracking(True)
        self.table.setHorizontalScrollMode(QTableView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QTableView.ScrollPerPixel)
        # The table grows with the window instead of being pinned to its content
        # size, so a long initiative order scrolls rather than running off-screen.
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.installEventFilter(self)

        self.mainlayout.addWidget(self.label_widget)
        self.mainlayout.addWidget(self.table, stretch=1)

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
        self.dam_layout.addWidget(turn_group)

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
        self.creature_list.setToolTip(
            "Select one or more combatants, then use the HP controls below"
        )
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
        self.dam_layout.addWidget(combatants_group, stretch=1)

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
        self.dam_layout.addWidget(hp_group)

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

        self.dam_layout.addWidget(hp_mods_group)

        self.dam_widget = QWidget()
        self.dam_widget.setLayout(self.dam_layout)
        self.dam_widget.setMinimumWidth(210)

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

    def _select_all_visible_creatures(self):
        for row in range(self.creature_list.count()):
            item = self.creature_list.item(row)
            if not item.isHidden():
                item.setSelected(True)

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
        self.monster_list.setMinimumHeight(80)
        self.monster_list.setMaximumHeight(140)
        self.monster_list.setToolTip("Pick a monster to show its statblock")
        self.monster_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.monster_list.customContextMenuRequested.connect(self._monster_list_context_menu)

        # Statblock fills available space; the picker is pinned underneath it.
        self.stat_layout.addWidget(self.statblock_widget, stretch=1)
        self.stat_layout.addWidget(self.monster_list)

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
        """Transient, in-window feedback that also lands in the status bar."""
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

    def show_status_message(self, msg: str, timeout_ms: int = 4000):
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(msg, timeout_ms)

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
        self.characters_menu = self.file_menu.addMenu("Characters")

        self.edit_menu = self.menu_bar.addMenu("&Edit")
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
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_action.setToolTip("Save current state (Ctrl+S)")
        self.file_menu.addAction(self.save_action)

        self.save_as_action = QAction('Save As', self)
        self.save_as_action.triggered.connect(self.save_as_encounter)
        self.save_as_action.setToolTip("Save current encounter as a new file")
        self.file_menu.addAction(self.save_as_action)

        self.file_menu.addSeparator()
        self.settings_action = QAction("Settings…", self)
        self.settings_action.triggered.connect(self.open_settings)
        self.file_menu.addAction(self.settings_action)

        self.customize_layout_action = QAction("Customize Layout…", self)
        self.customize_layout_action.setToolTip(
            "Choose where each panel sits, how wide it is, and where the toolbar goes"
        )
        self.customize_layout_action.triggered.connect(self.open_layout_settings)
        self.file_menu.addAction(self.customize_layout_action)

        self.customize_toolbar_action = QAction("Customize Toolbar…", self)
        self.customize_toolbar_action.triggered.connect(self.open_customize_toolbar)
        self.file_menu.addAction(self.customize_toolbar_action)

        self.customize_colors_action = QAction("Customize Colors…", self)
        self.customize_colors_action.setToolTip(
            "Change the turn, bloodied, down and dead row colours, and the theme"
        )
        self.customize_colors_action.triggered.connect(self.open_color_settings)
        self.file_menu.addAction(self.customize_colors_action)

        # PC Groups: quick-switch saved player rosters. The submenu is rebuilt
        # each time it opens so newly saved groups appear without a restart.
        self.groups_menu = self.file_menu.addMenu("PC Groups")
        self.groups_menu.aboutToShow.connect(self._populate_groups_menu)

        self.initialize_players_action = QAction("Initialize", self)
        self.initialize_players_action.triggered.connect(self.init_players)
        self.edit_menu.addAction(self.initialize_players_action)

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

        self.update_characters_action = QAction("Create/Update Characters", self)
        self.update_characters_action.triggered.connect(self.create_or_update_characters)
        self.characters_menu.addAction(self.update_characters_action)

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
        self.lookup_action.setShortcut(QKeySequence("Ctrl+L"))
        self.lookup_action.setToolTip("Look up spells, monsters, and conditions (Ctrl+L)")
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
        self.next_turn_action.setShortcut(QKeySequence("Ctrl+N"))
        self.next_turn_action.triggered.connect(self.next_turn)
        self.edit_menu.addAction(self.next_turn_action)

        self.prev_turn_action = QAction("Previous Turn", self)
        self.prev_turn_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
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

        self.view_menu.addSeparator()

        # Placement and sizing live in a dialog rather than being dragged, so
        # the layout can't be knocked out of shape by a stray mouse gesture.
        self.view_menu.addAction(self.customize_layout_action)
        self.view_menu.addAction(self.customize_toolbar_action)
        self.view_menu.addAction(self.customize_colors_action)

        self.reset_layout_action = QAction("Reset Panel Layout", self)
        self.reset_layout_action.setToolTip("Put every panel back to its default position")
        self.reset_layout_action.triggered.connect(self.reset_layout)
        self.view_menu.addAction(self.reset_layout_action)

    def _setup_help_menu(self):
        self.shortcuts_action = QAction("Keyboard Shortcuts", self)
        self.shortcuts_action.setShortcut(QKeySequence("F1"))
        self.shortcuts_action.triggered.connect(self.show_shortcuts)
        self.help_menu.addAction(self.shortcuts_action)

        self.show_log_action = QAction("Show Log…", self)
        self.show_log_action.setToolTip("Recent activity and errors — useful when reporting a bug")
        self.show_log_action.triggered.connect(self.show_log)
        self.help_menu.addAction(self.show_log_action)

        self.help_menu.addSeparator()

        # Carries the CC-BY-4.0 notice for the bundled SRD library, which has
        # to accompany the material in the distributed app, not just the repo.
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self.show_about)
        self.help_menu.addAction(self.about_action)

    def show_about(self):
        from ui.about_dialog import AboutDialog
        AboutDialog(self).exec_()

    def show_log(self):
        from ui.log_dialog import LogDialog
        LogDialog(self).exec_()

    def show_shortcuts(self):
        """A discoverable list of shortcuts — otherwise they're only in tooltips."""
        rows = [
            ("Ctrl+N", "Next turn"),
            ("Ctrl+Shift+N", "Previous turn"),
            ("Ctrl+S", "Save state"),
            ("Ctrl+L", "Reference lookup"),
            ("Ctrl+F", "Focus the combatant filter"),
            ("Ctrl +/-", "Zoom the statblock in/out (or Ctrl+scroll)"),
            ("Ctrl+0", "Reset statblock zoom"),
            ("Enter", "Damage selected (in the HP value box)"),
            ("Shift+Enter", "Heal selected (in the HP value box)"),
            ("Esc", "Clear selection / close dropdowns"),
            ("F1", "This list"),
        ]
        body = "\n".join(f"{key:<16}{label}" for key, label in rows)
        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard Shortcuts")
        layout = QVBoxLayout(dialog)
        view = QTextEdit(dialog)
        view.setReadOnly(True)
        view.setPlainText(body)
        view.setMinimumSize(400, 280)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, dialog)
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

    def show_hp_dropdown(self, creature, index):
        menu = QMenu(self)
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

        if getattr(creature, "_type", None) == CreatureType.MONSTER:
            visible = bool(getattr(creature, "player_visible", True))
            visibility_label = "Hide from Player View" if visible else "Reveal to Player View"
            visibility_action = menu.addAction(visibility_label)
        else:
            visibility_action = None

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

        if visibility_action and chosen == visibility_action:
            creature.player_visible = not bool(getattr(creature, "player_visible", True))
            self.table_model.refresh()
            self.update_table()
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
        self.save_layout()
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
        from PyQt5.QtCore import QEvent
        if hasattr(self, "value_input") and obj is self.value_input:
            if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    self.heal_selected_creatures()
                else:
                    self.damage_selected_creatures()
                return True

        if event.type() == event.MouseButtonPress:
            # If the click target is NOT inside the table, clear selection
            if hasattr(self, "table"):
                table_rect = self.table.rect()
                table_pos = self.table.mapFromGlobal(event.globalPos())

                if not table_rect.contains(table_pos):
                    self.table.clearSelection()
                    self.table.setCurrentIndex(self.table.model().index(-1, -1))

        return super().eventFilter(obj, event)
