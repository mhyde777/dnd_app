from typing import List
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QCheckBox,
    QGroupBox, QPushButton, QHBoxLayout, QGridLayout
)
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from PyQt5.QtGui import QColor

# === Foundry Conditions + Concentrating ===
DEFAULT_CONDITIONS: List[str] = [
    "Blinded",
    "Charmed",
    "Concentrating",
    "Deafened",
    "Exhaustion",
    "Frightened",
    "Grappled",
    "Incapacitated",
    "Invisible",
    "Paralyzed",
    "Petrified",
    "Poisoned",
    "Prone",
    "Restrained",
    "Stunned",
    "Unconscious",
]


class ConditionsDropdown(QFrame):
    """
    Popup dropdown to edit conditions for a single creature.
    Intended to be opened from the creature_list (double-click).
    """

    def __init__(self, creature, parent=None, condition_names: List[str] = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.creature = creature
        self._boxes = {}
        self._syncing = False

        names = condition_names or DEFAULT_CONDITIONS

        self.setFrameShape(QFrame.Box)
        self.setMinimumWidth(320)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        title = QLabel(f"Conditions: {getattr(creature, 'name', '')}")
        title.setStyleSheet("font-weight: bold;")
        root.addWidget(title)

        # 2-column grid layout (no scroll needed for 16 items)
        group = QGroupBox()
        grid = QGridLayout(group)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(4)

        cols = 2
        for i, name in enumerate(names):
            cb = QCheckBox(f"\u2022 {name}")
            cb.stateChanged.connect(self._on_change)
            self._boxes[name] = cb
            grid.addWidget(cb, i // cols, i % cols)

        root.addWidget(group)

        # Bottom buttons
        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._sync_from_creature()

    # ----------------------------
    # Internal helpers
    # ----------------------------
    def _sync_from_creature(self):
        self._syncing = True
        try:
            active = set(getattr(self.creature, "conditions", []) or [])
            for name, cb in self._boxes.items():
                cb.setChecked(name in active)
        finally:
            self._syncing = False

    def _write_to_creature(self):
        active = [name for name, cb in self._boxes.items() if cb.isChecked()]
        if hasattr(self.creature, "conditions"):
            self.creature.conditions = active
        else:
            setattr(self.creature, "_conditions", active)
        return active

    def _on_change(self, _state):
        if self._syncing:
            return
        previous = set(getattr(self.creature, "conditions", []) or [])
        active = set(self._write_to_creature())
        added = sorted(active - previous)
        removed = sorted(previous - active)

        # Refresh table if parent has one
        parent = self.parent()
        if parent and hasattr(parent, "table_model"):
            try:
                parent.table_model.refresh()
            except Exception:
                pass
        if parent and hasattr(parent, "_enqueue_bridge_condition_delta"):
            try:
                parent._enqueue_bridge_condition_delta(self.creature, added, removed)
            except Exception:
                pass

    def _clear_all(self):
        self._syncing = True
        try:
            for cb in self._boxes.values():
                cb.setChecked(False)
        finally:
            self._syncing = False

        previous = set(getattr(self.creature, "conditions", []) or [])
        self._write_to_creature()
        removed = sorted(previous)

        parent = self.parent()
        if parent and hasattr(parent, "table_model"):
            try:
                parent.table_model.refresh()
            except Exception:
                pass
        if parent and hasattr(parent, "_enqueue_bridge_condition_delta"):
            try:
                parent._enqueue_bridge_condition_delta(self.creature, [], removed)
            except Exception:
                pass
