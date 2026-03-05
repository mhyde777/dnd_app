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
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

import app.settings as settings

# ---- Registry ---------------------------------------------------------------
# All actions that *can* appear in the toolbar: (id, display label)
TOOLBAR_REGISTRY: list[tuple[str, str]] = [
    ("add_combatant",       "Add Combatant"),
    ("remove_combatants",   "Remove Combatants"),
    ("load_encounter",      "Load Encounter"),
    ("build_encounter",     "Build Encounter"),
    ("merge_encounters",    "Merge Encounters"),
    ("add_lair_action",     "Add Lair Action"),
    ("reference_lookup",    "Reference Lookup"),
    ("save",                "Save"),
    ("save_as",             "Save As"),
    ("initialize",          "Initialize Players"),
    ("next_turn",           "Next Turn"),
    ("prev_turn",           "Previous Turn"),
    ("activate_encounters", "Activate/Deactivate Encounters"),
    ("delete_encounter",    "Delete Encounter"),
    ("update_characters",   "Create/Update Characters"),
    ("import_statblock",    "Import Statblock"),
    ("import_spell",        "Import Spell"),
]

DEFAULT_TOOLBAR: list[str] = [
    "add_combatant",
    "remove_combatants",
    "merge_encounters",
    "add_lair_action",
    "reference_lookup",
]

_REGISTRY_MAP: dict[str, str] = {aid: label for aid, label in TOOLBAR_REGISTRY}
_VALID_IDS: set[str] = {aid for aid, _ in TOOLBAR_REGISTRY}


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
    Shows all toolbar-eligible actions as a checkable, draggable list.
    Checked = shown in toolbar. Order in list = order in toolbar.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Toolbar")
        self.setMinimumSize(360, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(QLabel(
            "Check items to show in the toolbar.\n"
            "Drag rows or use the arrows to reorder."
        ))

        # List + arrow buttons side by side
        list_row = QHBoxLayout()

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        list_row.addWidget(self.list_widget)

        arrow_col = QVBoxLayout()
        arrow_col.setSpacing(4)
        self.up_btn = QPushButton("▲")
        self.up_btn.setFixedWidth(32)
        self.up_btn.setToolTip("Move up")
        self.down_btn = QPushButton("▼")
        self.down_btn.setFixedWidth(32)
        self.down_btn.setToolTip("Move down")
        self.up_btn.clicked.connect(self._move_up)
        self.down_btn.clicked.connect(self._move_down)
        arrow_col.addStretch()
        arrow_col.addWidget(self.up_btn)
        arrow_col.addWidget(self.down_btn)
        arrow_col.addStretch()
        list_row.addLayout(arrow_col)

        root.addLayout(list_row)

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
        self.list_widget.clear()
        active_set = set(active)

        # Active items first (in saved order), then the rest alphabetically
        inactive = [
            (aid, label) for aid, label in TOOLBAR_REGISTRY
            if aid not in active_set
        ]
        ordered = [(aid, _REGISTRY_MAP[aid]) for aid in active if aid in _REGISTRY_MAP]

        for aid, label in ordered + inactive:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, aid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setCheckState(Qt.Checked if aid in active_set else Qt.Unchecked)
            self.list_widget.addItem(item)

    def _move_up(self) -> None:
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)

    def _restore_defaults(self) -> None:
        self._populate(DEFAULT_TOOLBAR)

    def _on_save(self) -> None:
        items = []
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.checkState() == Qt.Checked:
                items.append(it.data(Qt.UserRole))
        save_toolbar_items(items)
        self.accept()
