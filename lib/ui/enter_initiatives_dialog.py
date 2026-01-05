from typing import Dict, Iterable

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QSpinBox, QVBoxLayout,
)

from app.creature import Player


class EnterInitiativesDialog(QDialog):
    """
    Prompt for missing initiatives on loaded players.
    """

    def __init__(self, players: Iterable[Player], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Initiatives")

        layout = QVBoxLayout(self)

        info = QLabel(
            "Enter initiatives for players that were missing values in the loaded file."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._inputs: Dict[str, QSpinBox] = {}

        for player in players:
            row = QHBoxLayout()
            row.addWidget(QLabel(player.name))

            spin = QSpinBox()
            spin.setRange(1,50)
            spin.setValue(0)
            self._inputs[player.name] = spin
            row.addWidget(spin)

            layout.addLayout(row)

        button_box = QDialogButtonBox()
        button_box.addButton("Save", QDialogButtonBox.AcceptRole)
        button_box.addButton("Skip", QDialogButtonBox.RejectRole)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_initiatives(self) -> Dict[str, int]:
        """
        Return initiatives keyed by player name.
        """
        return {name: spin.value() for name, spin in self._input.items()}
