from __future__ import annotations
from typing import Dict, Iterable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QDialogButtonBox,
    QSpinBox,
    QWidget,
    QFormLayout,
)


class EnterInitiativesDialog(QDialog):
    """Prompt the user to enter initiatives for the given player creatures."""

    def __init__(self, players: Iterable, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Enter Player Initiatives")
        self.inputs: Dict[str, QSpinBox] = {}

        layout = QVBoxLayout(self)

        info = QLabel("Enter player initiatives before starting combat:")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        for player in sorted(players, key=lambda p: getattr(p, "name", "")):
            box = QSpinBox(self)
            box.setMinimum(-50)
            box.setMaximum(1000)
            current = getattr(player, "initiative", 0)
            if isinstance(current, int) and current > 0:
                box.setValue(int(current))
            else:
                box.setValue(10)
            box.setAlignment(Qt.AlignRight)
            self.inputs[getattr(player, "name", "")] = box
            label = getattr(player, "name", "Player") or "Player"
            form.addRow(label, box)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def initiatives(self) -> Dict[str, int]:
        """Return the initiatives keyed by player name."""
        return {name: spin.value() for name, spin in self.inputs.items()}
