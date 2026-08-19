# lib/ui/log_dialog.py
"""Help → Show Log: the in-app view of what the app has been doing."""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from app import app_log


class LogDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Application Log")
        self.setMinimumSize(760, 460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)

        header = QLabel(
            "Recent activity and errors. Include this when reporting a problem."
        )
        header.setWordWrap(True)
        root.addWidget(header)

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.TypeWriter)
        mono.setPointSize(9)
        self.view.setFont(mono)
        root.addWidget(self.view, stretch=1)

        path_label = QLabel(f"Log file: {app_log.LOG_PATH}")
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setStyleSheet("color: #a09c8c;")
        root.addWidget(path_label)

        buttons = QHBoxLayout()

        self.errors_only = QCheckBox("Errors and warnings only")
        self.errors_only.toggled.connect(self._refresh)
        buttons.addWidget(self.errors_only)
        buttons.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        buttons.addWidget(refresh_btn)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._copy)
        buttons.addWidget(copy_btn)

        open_btn = QPushButton("Open Log Folder")
        open_btn.clicked.connect(self._open_folder)
        buttons.addWidget(open_btn)

        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)

        root.addLayout(buttons)

        self._refresh()

    def _lines(self) -> list[str]:
        lines = app_log.recent()
        if self.errors_only.isChecked():
            lines = [l for l in lines if " ERROR " in l or " WARNING " in l or " CRITICAL " in l]
        return lines

    def _refresh(self) -> None:
        lines = self._lines()
        self.view.setPlainText(
            "\n".join(lines) if lines else "(nothing logged yet this session)"
        )
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _copy(self) -> None:
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(self._lines()))
        from ui.notifications import toast

        toast(self, "Log copied to clipboard", "success")

    def _open_folder(self) -> None:
        folder = os.path.dirname(app_log.LOG_PATH)
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
