# lib/ui/control_sections_dialog.py
"""
Which sections of the Combat Controls dock are shown, and in what order.

Same contract as the toolbar registry: an id here must have a matching entry in
`_control_sections` (lib/ui/ui.py). Hiding a section only takes it off screen --
nothing it did becomes unreachable, since HP mods live in the HP cell's popup
and combatants can be targeted by selecting rows in the initiative table.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
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

_SETTING_KEY = "control_sections"

# (id, label, what it's for -- shown as the row's tooltip)
CONTROL_SECTION_REGISTRY: list[tuple[str, str, str]] = [
    ("turn_controls", "Turn Controls",
     "Previous / Next turn. Also on the toolbar and the keyboard."),
    ("combatants", "Combatants",
     "The filterable pick list. Rows in the initiative table select the same "
     "targets, so the HP controls still work without it."),
    ("hp_controls", "HP Controls",
     "The damage / heal box for everything selected."),
    ("hp_mods", "HP Mods",
     "Temp HP and Max HP bonus. Also on each creature's HP cell popup."),
]

DEFAULT_CONTROL_SECTIONS: list[str] = [key for key, _label, _tip in CONTROL_SECTION_REGISTRY]

_LABELS: dict[str, str] = {key: label for key, label, _tip in CONTROL_SECTION_REGISTRY}
_TOOLTIPS: dict[str, str] = {key: tip for key, _label, tip in CONTROL_SECTION_REGISTRY}
_VALID_IDS: set[str] = set(_LABELS)


# ---- Persistence helpers ----------------------------------------------------

def load_control_sections() -> list[str]:
    """The visible sections, in display order. Unknown ids are dropped."""
    saved = settings.get(_SETTING_KEY)
    if saved is None:
        return list(DEFAULT_CONTROL_SECTIONS)
    if not isinstance(saved, list):
        return list(DEFAULT_CONTROL_SECTIONS)
    seen: list[str] = []
    for key in saved:
        if key in _VALID_IDS and key not in seen:
            seen.append(key)
    return seen


def save_control_sections(order: list[str]) -> None:
    data = dict(settings.load())
    if order == DEFAULT_CONTROL_SECTIONS:
        data.pop(_SETTING_KEY, None)
    else:
        data[_SETTING_KEY] = list(order)
    settings.save(data)


def ordered_all(visible: list[str]) -> list[str]:
    """Visible sections in their chosen order, then the hidden ones.

    The hidden ones still go into the layout (hidden widgets take no space), so
    showing one again is a setVisible call rather than a rebuild.
    """
    hidden = [key for key in DEFAULT_CONTROL_SECTIONS if key not in visible]
    return list(visible) + hidden


# ---- Dialog -----------------------------------------------------------------

class ControlSectionsDialog(QDialog):
    """Tick what to show, drag or use the buttons to order it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Combat Controls")
        self.setMinimumSize(420, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._tracker = parent

        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "Untick a section to hide it, and drag to reorder. Nothing becomes "
            "unreachable — HP mods are also on each creature's HP cell, and the "
            "initiative table selects the same targets as the combatant list."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        root.addWidget(self._list, stretch=1)

        visible = load_control_sections()
        for key in ordered_all(visible):
            item = QListWidgetItem(_LABELS[key])
            item.setData(Qt.UserRole, key)
            item.setToolTip(_TOOLTIPS[key])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if key in visible else Qt.Unchecked)
            self._list.addItem(item)

        move_row = QHBoxLayout()
        up = QPushButton("Move Up")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("Move Down")
        down.clicked.connect(lambda: self._move(1))
        move_row.addWidget(up)
        move_row.addWidget(down)
        move_row.addStretch()
        root.addLayout(move_row)

        bottom = QHBoxLayout()
        restore = QPushButton("Restore Defaults")
        restore.clicked.connect(self._restore_defaults)
        bottom.addWidget(restore)
        bottom.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        root.addLayout(bottom)

    # ---- helpers ------------------------------------------------------------

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self._list.count()):
            return
        item = self._list.takeItem(row)
        self._list.insertItem(target, item)
        self._list.setCurrentRow(target)

    def _restore_defaults(self) -> None:
        self._list.clear()
        for key in DEFAULT_CONTROL_SECTIONS:
            item = QListWidgetItem(_LABELS[key])
            item.setData(Qt.UserRole, key)
            item.setToolTip(_TOOLTIPS[key])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._list.addItem(item)

    def values(self) -> list[str]:
        return [
            self._list.item(row).data(Qt.UserRole)
            for row in range(self._list.count())
            if self._list.item(row).checkState() == Qt.Checked
        ]

    def _on_save(self) -> None:
        save_control_sections(self.values())
        tracker = self._tracker
        if tracker is not None and hasattr(tracker, "apply_control_sections"):
            tracker.apply_control_sections()
        self.accept()
