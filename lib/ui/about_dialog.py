"""
Help → About.

This dialog is not decoration. The bundled SRD library is used under
CC-BY-4.0, which requires the attribution notice to travel with the material
wherever it is distributed — putting it only in a repository file would not
cover the packaged application. If the SRD payload ships, this notice ships.

The AI-assistance disclosure is here for the same reason: someone running the
packaged app has no reason to read the repository, and a disclosure only they
can't see is not a disclosure.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QVBoxLayout,
)

from app import srd_content
from app.version import __version__

# Wizards' terms permit describing a work as fifth-edition compatible but
# forbid any other attribution to them, so this wording is deliberate.
_COMPAT = (
    'Compatible with fifth edition. Not affiliated with, or endorsed by, '
    'Wizards of the Coast.'
)


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("D&D Combat Tracker")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        root.addWidget(QLabel(f"Version {__version__}"))

        summary = QLabel(
            "Initiative, hit points, conditions and combat state for D&D 5e, "
            "with optional two-way sync to Foundry VTT."
        )
        summary.setWordWrap(True)
        root.addWidget(summary)

        root.addWidget(self._separator())
        built_with = QLabel(
            "Built by mhyde777 with substantial help from AI coding assistants "
            "(Anthropic's Claude), which wrote or reworked much of the code "
            "under direction and review. Design decisions, testing and "
            "everything it does at the table are the author's."
        )
        built_with.setWordWrap(True)
        built_with.setStyleSheet("color: #999; font-size: 11px;")
        root.addWidget(built_with)

        if srd_content.is_available():
            root.addWidget(self._separator())

            counts = srd_content.counts()
            included = QLabel(
                f"Includes {counts.get('statblocks', 0)} monsters and "
                f"{counts.get('spells', 0)} spells from the "
                "System Reference Document 5.2.1."
            )
            included.setWordWrap(True)
            root.addWidget(included)

            notice = QLabel(srd_content.attribution() or _FALLBACK_ATTRIBUTION)
            notice.setWordWrap(True)
            notice.setOpenExternalLinks(True)
            notice.setTextInteractionFlags(Qt.TextBrowserInteraction)
            notice.setStyleSheet("color: #999; font-size: 11px;")
            root.addWidget(notice)

            licence_link = QLabel(
                'Licensed under '
                '<a href="https://creativecommons.org/licenses/by/4.0/legalcode">'
                "CC-BY-4.0</a>."
            )
            licence_link.setOpenExternalLinks(True)
            licence_link.setStyleSheet("color: #999; font-size: 11px;")
            root.addWidget(licence_link)

        root.addWidget(self._separator())

        compat = QLabel(_COMPAT)
        compat.setWordWrap(True)
        compat.setStyleSheet("color: #999; font-size: 11px;")
        root.addWidget(compat)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line


# Used only if the manifest is unreadable; the notice must never be missing
# while the content it covers is present.
_FALLBACK_ATTRIBUTION = (
    'This work includes material from the System Reference Document 5.2.1 '
    '("SRD 5.2.1") by Wizards of the Coast LLC, available at '
    "https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the "
    "Creative Commons Attribution 4.0 International License."
)
