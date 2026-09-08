# lib/ui/install_details_dialog.py
"""
Help → Installation Details.

The update dialog says whether it can install in place and gives one sentence
when it cannot. That sentence names a cause but not the state it came from, so
"updating doesn't work" stayed hard to act on — especially on Windows, where
the answer usually turns on something invisible from inside the app: an install
extracted into a directory the user cannot write to, or an old flat layout with
no launcher.

This shows the state each check was derived from, and copies it as text so it
can go straight into a bug report.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app import install_diagnostics


class InstallDetailsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installation Details")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)

        self._rows = install_diagnostics.collect()
        can = dict(self._rows).get("Can install updates") == "yes"

        headline = QLabel(
            "This copy can install updates itself."
            if can else
            "This copy cannot install updates itself."
        )
        headline.setStyleSheet(
            "font-weight: bold; padding-bottom: 4px;"
            + ("" if can else " color: #e67e22;")
        )
        layout.addWidget(headline)

        if not can:
            reason = dict(self._rows).get("Reason", "")
            explain = QLabel(
                f"{reason}\n\nHelp → Check for Updates will still download the "
                "new version to your Downloads folder; it just cannot install "
                "it for you."
            )
            explain.setWordWrap(True)
            layout.addWidget(explain)

        table = QTableWidget(len(self._rows), 2, self)
        table.setHorizontalHeaderLabels(["", ""])
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setShowGrid(False)
        for row, (label, value) in enumerate(self._rows):
            name = QTableWidgetItem(label)
            name.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 0, name)
            # Paths are long and the interesting part is the end of them, so
            # the value column is the one that gets the space.
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setToolTip(value)
            table.setItem(row, 1, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(table)

        buttons = QHBoxLayout()
        copy_btn = QPushButton("Copy")
        copy_btn.setToolTip("Copy these details, for pasting into a bug report")
        copy_btn.clicked.connect(self._copy)
        buttons.addWidget(copy_btn)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._copy_btn = copy_btn

    def _copy(self) -> None:
        QApplication.clipboard().setText(install_diagnostics.as_text())
        # Confirming in the button itself rather than with a toast: the dialog
        # is modal, so a toast behind it would not be seen.
        self._copy_btn.setText("Copied")
        self._copy_btn.setEnabled(False)
