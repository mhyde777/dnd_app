from typing import List
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QCheckBox,
    QScrollArea, QGroupBox, QPushButton, QHBoxLayout
)

# === 2024 PHB Conditions + Concentrating ===
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

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        title = QLabel(f"Conditions: {getattr(creature, 'name', '')}")
        title.setStyleSheet("font-weight: bold;")
        root.addWidget(title)

        group = QGroupBox()
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(6, 6, 6, 6)
        group_layout.setSpacing(4)

        for name in names:
            cb = QCheckBox(name)
            cb.stateChanged.connect(self._on_change)
            self._boxes[name] = cb
            group_layout.addWidget(cb)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(group)
        scroll.setMinimumWidth(220)
        scroll.setMinimumHeight(260)
        root.addWidget(scroll)

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
