# lib/ui/toolbar_customize_dialog.py
"""
Dialog for customizing which actions appear in the toolbar and in what order.

Usage:
    dlg = ToolbarCustomizeDialog(parent)
    if dlg.exec_() == QDialog.Accepted:
        parent._apply_toolbar_config()
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

import app.settings as settings

# ---- Registry ---------------------------------------------------------------
# Every action that *can* appear in the toolbar: (id, display label, group)
TOOLBAR_REGISTRY: list[tuple[str, str, str]] = [
    ("next_turn",           "Next Turn",                     "Combat"),
    ("prev_turn",           "Previous Turn",                 "Combat"),
    ("initialize",          "Initialize Players",            "Combat"),
    ("add_combatant",       "Add Combatant",                 "Combat"),
    ("remove_combatants",   "Remove Combatants",             "Combat"),
    ("add_lair_action",     "Add Lair Action",               "Combat"),

    ("save",                "Save",                          "Encounters"),
    ("save_as",             "Save As",                       "Encounters"),
    ("load_encounter",      "Load Encounter",                "Encounters"),
    ("build_encounter",     "Build Encounter",               "Encounters"),
    ("merge_encounters",    "Merge Encounters",              "Encounters"),
    ("activate_encounters", "Activate/Deactivate Encounters", "Encounters"),
    ("delete_encounter",    "Delete Encounter",              "Encounters"),

    ("reference_lookup",    "Reference Lookup",              "Content"),
    ("update_characters",   "Create/Update Characters",      "Content"),
    ("import_statblock",    "Import Statblock",              "Content"),
    ("import_spell",        "Import Spell",                  "Content"),
    ("bulk_import_items",   "Bulk Import Items",             "Content"),
    ("shop_generator",      "Shop Generator",                "Content"),

    ("separator",           "── Separator ──",               "Layout"),

    ("settings",            "Settings",                      "App"),
    ("foundry_ignore",      "Foundry Ignore List",           "App"),
    ("show_log",            "Show Log",                      "App"),
]

DEFAULT_TOOLBAR: list[str] = [
    "add_combatant",
    "remove_combatants",
    "merge_encounters",
    "add_lair_action",
    "reference_lookup",
]

_REGISTRY_MAP: dict[str, str] = {aid: label for aid, label, _ in TOOLBAR_REGISTRY}
_VALID_IDS: set[str] = {aid for aid, _, _ in TOOLBAR_REGISTRY}

# "separator" is a spacer, not a command, so it may legitimately repeat.
REPEATABLE_IDS: set[str] = {"separator"}


# ---- Persistence helpers ----------------------------------------------------

def load_toolbar_items() -> list[str]:
    """Return the ordered list of action IDs currently enabled in the toolbar."""
    saved = settings.get("toolbar_items")
    if saved is None:
        return list(DEFAULT_TOOLBAR)
    return [x for x in saved if x in _VALID_IDS]


def save_toolbar_items(items: list[str]) -> None:
    data = dict(settings.load())
    data["toolbar_items"] = items
    settings.save(data)


# ---- Dialog -----------------------------------------------------------------

class ToolbarCustomizeDialog(QDialog):
    """
    Two-pane customizer: pick from the grouped list of available commands on the
    left, arrange the toolbar on the right.

    This shape (rather than one checkable list) is what lets a command be found
    by searching and lets separators appear more than once.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Toolbar")
        self.setMinimumSize(640, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(QLabel(
            "Add the commands you use most to the toolbar, then drag to reorder."
        ))

        panes = QHBoxLayout()
        panes.setSpacing(8)

        # --- Available ---
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(QLabel("Available commands"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_available)
        left.addWidget(self.search)
        self.available = QListWidget()
        self.available.setSelectionMode(QListWidget.ExtendedSelection)
        self.available.itemDoubleClicked.connect(lambda _: self._add_selected())
        left.addWidget(self.available)
        panes.addLayout(left, stretch=1)

        # --- Add / remove ---
        middle = QVBoxLayout()
        middle.addStretch()
        self.add_btn = QPushButton("Add  ▶")
        self.add_btn.clicked.connect(self._add_selected)
        self.remove_btn = QPushButton("◀  Remove")
        self.remove_btn.clicked.connect(self._remove_selected)
        middle.addWidget(self.add_btn)
        middle.addWidget(self.remove_btn)
        middle.addStretch()
        panes.addLayout(middle)

        # --- Current toolbar ---
        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(QLabel("On the toolbar"))

        current_row = QHBoxLayout()
        self.current = QListWidget()
        self.current.setDragDropMode(QListWidget.InternalMove)
        self.current.setDefaultDropAction(Qt.MoveAction)
        self.current.setSelectionMode(QListWidget.SingleSelection)
        self.current.itemDoubleClicked.connect(lambda _: self._remove_selected())
        current_row.addWidget(self.current)

        arrow_col = QVBoxLayout()
        arrow_col.setSpacing(4)
        self.up_btn = QPushButton("▲")
        self.up_btn.setFixedWidth(32)
        self.up_btn.setToolTip("Move up")
        self.up_btn.clicked.connect(self._move_up)
        self.down_btn = QPushButton("▼")
        self.down_btn.setFixedWidth(32)
        self.down_btn.setToolTip("Move down")
        self.down_btn.clicked.connect(self._move_down)
        arrow_col.addStretch()
        arrow_col.addWidget(self.up_btn)
        arrow_col.addWidget(self.down_btn)
        arrow_col.addStretch()
        current_row.addLayout(arrow_col)

        right.addLayout(current_row)
        panes.addLayout(right, stretch=1)

        root.addLayout(panes, stretch=1)

        # Bottom button row
        bottom = QHBoxLayout()
        restore_btn = QPushButton("Restore Defaults")
        restore_btn.clicked.connect(self._restore_defaults)
        bottom.addWidget(restore_btn)
        bottom.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        bottom.addWidget(btn_box)
        root.addLayout(bottom)

        self._populate(load_toolbar_items())

    # ---- internal ----

    def _populate(self, active: list[str]) -> None:
        self.current.clear()
        for aid in active:
            if aid in _REGISTRY_MAP:
                self.current.addItem(self._make_item(aid))
        self._rebuild_available()

    def _make_item(self, aid: str) -> QListWidgetItem:
        item = QListWidgetItem(_REGISTRY_MAP[aid])
        item.setData(Qt.UserRole, aid)
        return item

    def _rebuild_available(self) -> None:
        """Available = everything not already on the toolbar, grouped."""
        used = {
            self.current.item(i).data(Qt.UserRole)
            for i in range(self.current.count())
        }
        self.available.clear()
        last_group = None
        for aid, label, group in TOOLBAR_REGISTRY:
            if aid in used and aid not in REPEATABLE_IDS:
                continue
            if group != last_group:
                heading = QListWidgetItem(group.upper())
                heading.setFlags(Qt.NoItemFlags)  # a label, not a choice
                self.available.addItem(heading)
                last_group = group
            self.available.addItem(self._make_item(aid))
        self._filter_available(self.search.text())

    def _filter_available(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for i in range(self.available.count()):
            item = self.available.item(i)
            if item.flags() == Qt.NoItemFlags:
                # Hide group headings while searching so results read as one list.
                item.setHidden(bool(needle))
                continue
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _add_selected(self) -> None:
        added = False
        for item in self.available.selectedItems():
            aid = item.data(Qt.UserRole)
            if not aid:
                continue
            self.current.addItem(self._make_item(aid))
            added = True
        if added:
            self._rebuild_available()
            self.current.setCurrentRow(self.current.count() - 1)

    def _remove_selected(self) -> None:
        row = self.current.currentRow()
        if row < 0:
            return
        self.current.takeItem(row)
        self._rebuild_available()
        self.current.setCurrentRow(min(row, self.current.count() - 1))

    def _move_up(self) -> None:
        row = self.current.currentRow()
        if row > 0:
            item = self.current.takeItem(row)
            self.current.insertItem(row - 1, item)
            self.current.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self.current.currentRow()
        if 0 <= row < self.current.count() - 1:
            item = self.current.takeItem(row)
            self.current.insertItem(row + 1, item)
            self.current.setCurrentRow(row + 1)

    def _restore_defaults(self) -> None:
        self._populate(DEFAULT_TOOLBAR)

    def _on_save(self) -> None:
        items = [
            self.current.item(i).data(Qt.UserRole)
            for i in range(self.current.count())
        ]
        save_toolbar_items([i for i in items if i])
        self.accept()
