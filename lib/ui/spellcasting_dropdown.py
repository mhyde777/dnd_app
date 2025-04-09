from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QCheckBox, QGroupBox
)
from PyQt5.QtCore import Qt

class SpellcastingDropdown(QWidget):
    def __init__(self, creature, parent=None):
        super().__init__(parent)
        self.creature = creature
        self.innate_checkboxes = {}  # spell -> list of QCheckBox
        self.slot_checkboxes = {}    # level -> list of QCheckBox

        self.setLayout(QVBoxLayout())

        # === Cantrips (usage == -1)
        cantrips = {spell: uses for spell, uses in creature._innate_slots.items() if uses == -1}
        if cantrips:
            cantrip_group = QGroupBox("Cantrips (At Will)")
            cantrip_layout = QVBoxLayout()
            for spell in sorted(cantrips.keys()):
                cantrip_layout.addWidget(QLabel(f"- {spell}"))
            cantrip_group.setLayout(cantrip_layout)
            self.layout().addWidget(cantrip_group)

        # === Innate Spells
        innate_spells = {spell: uses for spell, uses in creature._innate_slots.items() if uses > 0}
        if innate_spells:
            innate_group = QGroupBox("Innate Spells")
            innate_layout = QVBoxLayout()
            for spell, uses in sorted(innate_spells.items()):
                row = QHBoxLayout()
                row.addWidget(QLabel(spell))
                self.innate_checkboxes[spell] = []
                for i in range(uses):
                    checkbox = QCheckBox()
                    if i < creature._innate_slots_used.get(spell, 0):
                        checkbox.setChecked(True)
                    self.innate_checkboxes[spell].append(checkbox)
                    row.addWidget(checkbox)
                row.addStretch()
                innate_layout.addLayout(row)
            innate_group.setLayout(innate_layout)
            self.layout().addWidget(innate_group)

        # === Spell Slots
        if creature._spell_slots:
            slot_group = QGroupBox("Spell Slots")
            slot_layout = QVBoxLayout()
            for level in sorted(creature._spell_slots.keys()):
                row = QHBoxLayout()
                row.addWidget(QLabel(f"Level {level}"))
                self.slot_checkboxes[level] = []
                for i in range(creature._spell_slots[level]):
                    checkbox = QCheckBox()
                    if i < creature._spell_slots_used.get(level, 0):
                        checkbox.setChecked(True)
                    self.slot_checkboxes[level].append(checkbox)
                    row.addWidget(checkbox)
                row.addStretch()
                slot_layout.addLayout(row)
            slot_group.setLayout(slot_layout)
            self.layout().addWidget(slot_group)

        # Now that all checkboxes are added, connect callbacks
        for spell, boxes in self.innate_checkboxes.items():
            for box in boxes:
                box.stateChanged.connect(self.make_innate_callback(spell))

        for level, boxes in self.slot_checkboxes.items():
            for box in boxes:
                box.stateChanged.connect(self.make_slot_callback(level))

        self.setWindowFlags(Qt.Popup)
        self.adjustSize()

    def make_innate_callback(self, spell):
        return lambda state: self.update_innate_usage(spell)

    def make_slot_callback(self, level):
        return lambda state: self.update_slot_usage(level)

    def update_innate_usage(self, spell):
        checked_count = sum(1 for box in self.innate_checkboxes.get(spell, []) if box.isChecked())
        self.creature._innate_slots_used[spell] = checked_count
        # print("[INNATE UPDATED]", spell, checked_count)

    def update_slot_usage(self, level):
        checked_count = sum(1 for box in self.slot_checkboxes.get(level, []) if box.isChecked())
        self.creature._spell_slots_used[level] = checked_count
        # print("[SLOTS UPDATED]", level, checked_count)
