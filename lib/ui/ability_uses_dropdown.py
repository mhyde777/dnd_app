from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QCheckBox, QGroupBox
)
from PyQt5.QtCore import Qt


class AbilityUsesDropdown(QWidget):
    def __init__(self, creature, parent=None):
        super().__init__(parent)
        self.creature = creature
        self.ability_checkboxes = {}  # name -> list of QCheckBox

        self.setLayout(QVBoxLayout())

        ability_uses = getattr(creature, "_ability_uses", {}) or {}

        # === Legendary Actions pool (if present)
        if "Legendary Actions" in ability_uses:
            count = ability_uses["Legendary Actions"]
            la_group = QGroupBox(f"Legendary Actions ({count}/round)")
            la_layout = QHBoxLayout()
            self.ability_checkboxes["Legendary Actions"] = []
            used = getattr(creature, "_ability_uses_used", {}).get("Legendary Actions", 0)
            for i in range(count):
                cb = QCheckBox()
                if i < used:
                    cb.setChecked(True)
                self.ability_checkboxes["Legendary Actions"].append(cb)
                la_layout.addWidget(cb)
            la_layout.addStretch()
            la_group.setLayout(la_layout)
            self.layout().addWidget(la_group)

        # === Limited Abilities (all non-Legendary Actions keys)
        limited = {k: v for k, v in ability_uses.items() if k != "Legendary Actions"}
        if limited:
            ltd_group = QGroupBox("Limited Abilities")
            ltd_layout = QVBoxLayout()
            used_map = getattr(creature, "_ability_uses_used", {}) or {}
            for name, max_uses in sorted(limited.items()):
                row = QHBoxLayout()
                row.addWidget(QLabel(name))
                self.ability_checkboxes[name] = []
                used = used_map.get(name, 0)
                for i in range(max_uses):
                    cb = QCheckBox()
                    if i < used:
                        cb.setChecked(True)
                    self.ability_checkboxes[name].append(cb)
                    row.addWidget(cb)
                row.addStretch()
                ltd_layout.addLayout(row)
            ltd_group.setLayout(ltd_layout)
            self.layout().addWidget(ltd_group)

        # Connect callbacks after all checkboxes are built
        for name, boxes in self.ability_checkboxes.items():
            for box in boxes:
                box.stateChanged.connect(self._make_callback(name))

        self.setWindowFlags(Qt.Popup)
        self.adjustSize()

    def _make_callback(self, name):
        return lambda state: self._update_usage(name)

    def _update_usage(self, name):
        checked = sum(1 for cb in self.ability_checkboxes.get(name, []) if cb.isChecked())
        self.creature._ability_uses_used[name] = checked
