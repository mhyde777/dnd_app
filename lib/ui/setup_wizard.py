# lib/ui/setup_wizard.py
"""
First-run setup wizard (also opened from File → Settings).

Prompts the user to choose between local file storage and a remote API
server, and saves the result to ~/.dnd_tracker_config/settings.json.
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

import app.settings as settings

_DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".dnd_tracker_config", "data")


class SetupWizard(QDialog):
    """Storage configuration dialog — shown on first run and from File → Settings."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("D&D Combat Tracker — Settings")
        self.setMinimumWidth(520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(14)

        title = QLabel("Storage Settings")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        root.addWidget(title)

        info = QLabel(
            "Choose where to store encounters, monsters, spells, and other data.\n"
            "You can reopen this dialog at any time via File → Settings."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # --- Storage mode radio buttons ---
        mode_box = QGroupBox("Storage Mode")
        mode_layout = QVBoxLayout(mode_box)
        self.local_radio = QRadioButton("Local Files  (store data on this computer)")
        self.api_radio = QRadioButton("Remote API Server  (connect to your own server)")
        self._btn_group = QButtonGroup(self)
        self._btn_group.addButton(self.local_radio)
        self._btn_group.addButton(self.api_radio)
        self.local_radio.setChecked(True)
        mode_layout.addWidget(self.local_radio)
        mode_layout.addWidget(self.api_radio)
        root.addWidget(mode_box)

        # --- Local section ---
        self.local_box = QGroupBox("Local Data Directory")
        local_layout = QHBoxLayout(self.local_box)
        self.local_dir_edit = QLineEdit()
        self.local_dir_edit.setPlaceholderText(_DEFAULT_DATA_DIR)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        local_layout.addWidget(self.local_dir_edit)
        local_layout.addWidget(browse_btn)
        root.addWidget(self.local_box)

        # --- API section ---
        self.api_box = QGroupBox("Remote API Settings")
        api_layout = QVBoxLayout(self.api_box)

        row_url = QHBoxLayout()
        lbl_url = QLabel("API URL:")
        lbl_url.setFixedWidth(65)
        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("http://192.168.1.100:8000")
        row_url.addWidget(lbl_url)
        row_url.addWidget(self.api_url_edit)
        api_layout.addLayout(row_url)

        row_key = QHBoxLayout()
        lbl_key = QLabel("API Key:")
        lbl_key.setFixedWidth(65)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        row_key.addWidget(lbl_key)
        row_key.addWidget(self.api_key_edit)
        api_layout.addLayout(row_key)

        self.api_box.setVisible(False)
        root.addWidget(self.api_box)

        self.local_radio.toggled.connect(self._on_mode_changed)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setDefault(True)
        self.save_btn.setMinimumWidth(120)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)

        self._prefill()

    # ---- slots ----

    def _on_mode_changed(self, local: bool) -> None:
        self.local_box.setVisible(local)
        self.api_box.setVisible(not local)

    def _browse(self) -> None:
        start = self.local_dir_edit.text() or _DEFAULT_DATA_DIR
        d = QFileDialog.getExistingDirectory(self, "Select Data Directory", start)
        if d:
            self.local_dir_edit.setText(d)

    def _prefill(self) -> None:
        import os
        # Prefer saved settings, fall back to existing env vars so first-run
        # users don't have to retype values that are already in their .env.
        mode = settings.get("storage_mode")
        if mode is None:
            env_api = os.getenv("USE_STORAGE_API_ONLY", "0").strip()
            mode = "api" if env_api not in ("", "0", "false", "False") else "local"

        if mode == "api":
            self.api_radio.setChecked(True)
            self._on_mode_changed(False)

        local_dir = settings.get("local_data_dir") or os.getenv("LOCAL_DATA_DIR", "")
        api_url = settings.get("storage_api_base") or os.getenv("STORAGE_API_BASE", "")
        api_key = settings.get("storage_api_key") or os.getenv("STORAGE_API_KEY", "")

        self.local_dir_edit.setText(local_dir)
        self.api_url_edit.setText(api_url)
        self.api_key_edit.setText(api_key)

    def _on_save(self) -> None:
        if self.api_radio.isChecked():
            url = self.api_url_edit.text().strip()
            if not url:
                QMessageBox.warning(self, "Missing URL", "Please enter the API URL.")
                return
            settings.save({
                "storage_mode": "api",
                "storage_api_base": url,
                "storage_api_key": self.api_key_edit.text().strip(),
            })
        else:
            settings.save({
                "storage_mode": "local",
                "local_data_dir": self.local_dir_edit.text().strip(),
            })
        self.accept()
