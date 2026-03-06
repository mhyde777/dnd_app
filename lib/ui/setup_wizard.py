# lib/ui/setup_wizard.py
"""
Settings dialog — shown on first run and from File -> Settings.

Contains two sections:
  1. Storage  — local files vs remote API server
  2. Foundry Bridge — how (or whether) to sync with Foundry VTT
"""
from __future__ import annotations

import os
import threading

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
    QTextEdit,
    QVBoxLayout,
)

import app.settings as settings

_DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".dnd_tracker_config", "data")


class SetupWizard(QDialog):
    """Storage + Bridge configuration dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("D&D Combat Tracker — Settings")
        self.setMinimumWidth(540)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(14)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        root.addWidget(title)

        info = QLabel(
            "Configure storage and Foundry VTT integration.\n"
            "You can reopen this dialog at any time via File \u2192 Settings."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        root.addWidget(_separator())

        # ── Storage ──────────────────────────────────────────────────────────
        storage_label = QLabel("Storage")
        storage_label.setStyleSheet("font-weight: bold;")
        root.addWidget(storage_label)

        mode_box = QGroupBox("Storage Mode")
        mode_layout = QVBoxLayout(mode_box)
        self.local_radio = QRadioButton("Local Files  (store data on this computer)")
        self.api_radio = QRadioButton("Remote API Server  (connect to your own server)")
        self._storage_group = QButtonGroup(self)
        self._storage_group.addButton(self.local_radio)
        self._storage_group.addButton(self.api_radio)
        self.local_radio.setChecked(True)
        mode_layout.addWidget(self.local_radio)
        mode_layout.addWidget(self.api_radio)
        root.addWidget(mode_box)

        # Local dir
        self.local_box = QGroupBox("Local Data Directory")
        local_layout = QHBoxLayout(self.local_box)
        self.local_dir_edit = QLineEdit()
        self.local_dir_edit.setPlaceholderText(_DEFAULT_DATA_DIR)
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        local_layout.addWidget(self.local_dir_edit)
        local_layout.addWidget(browse_btn)
        root.addWidget(self.local_box)

        # Remote API
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

        self.local_radio.toggled.connect(self._on_storage_mode_changed)

        root.addWidget(_separator())

        # ── Foundry Bridge ───────────────────────────────────────────────────
        bridge_label = QLabel("Foundry VTT Integration")
        bridge_label.setStyleSheet("font-weight: bold;")
        root.addWidget(bridge_label)

        bridge_box = QGroupBox("Bridge Mode")
        bridge_layout = QVBoxLayout(bridge_box)

        self.bridge_disabled_radio = QRadioButton("Disabled  (no Foundry sync)")
        self.bridge_local_radio = QRadioButton(
            "Local Bridge  (Foundry running on this machine)"
        )
        self.bridge_http_radio = QRadioButton(
            "HTTP Bridge Service  (remote Foundry via tunnel — configure in .env)"
        )
        self.bridge_socket_radio = QRadioButton(
            "Foundry Direct  (connect directly to remote Foundry via socket.io)"
        )

        self._bridge_group = QButtonGroup(self)
        for btn in (
            self.bridge_disabled_radio,
            self.bridge_local_radio,
            self.bridge_http_radio,
            self.bridge_socket_radio,
        ):
            self._bridge_group.addButton(btn)
            bridge_layout.addWidget(btn)

        self.bridge_local_radio.setChecked(True)
        root.addWidget(bridge_box)

        # Foundry Direct credentials box
        self.foundry_box = QGroupBox("Foundry Direct Settings")
        foundry_layout = QVBoxLayout(self.foundry_box)

        row_furl = QHBoxLayout()
        lbl_furl = QLabel("Foundry URL:")
        lbl_furl.setFixedWidth(110)
        self.foundry_url_edit = QLineEdit()
        self.foundry_url_edit.setPlaceholderText("https://your-foundry-server.com")
        row_furl.addWidget(lbl_furl)
        row_furl.addWidget(self.foundry_url_edit)
        foundry_layout.addLayout(row_furl)

        row_fusr = QHBoxLayout()
        lbl_fusr = QLabel("Username:")
        lbl_fusr.setFixedWidth(110)
        self.foundry_user_edit = QLineEdit()
        self.foundry_user_edit.setPlaceholderText("Gamemaster")
        row_fusr.addWidget(lbl_fusr)
        row_fusr.addWidget(self.foundry_user_edit)
        foundry_layout.addLayout(row_fusr)

        row_fpw = QHBoxLayout()
        lbl_fpw = QLabel("Password:")
        lbl_fpw.setFixedWidth(110)
        self.foundry_pw_edit = QLineEdit()
        self.foundry_pw_edit.setEchoMode(QLineEdit.Password)
        self.foundry_pw_edit.setPlaceholderText("(leave blank if no password set)")
        row_fpw.addWidget(lbl_fpw)
        row_fpw.addWidget(self.foundry_pw_edit)
        foundry_layout.addLayout(row_fpw)

        row_fuid = QHBoxLayout()
        lbl_fuid = QLabel("User ID:")
        lbl_fuid.setFixedWidth(110)
        self.foundry_uid_edit = QLineEdit()
        self.foundry_uid_edit.setPlaceholderText("(Foundry v13+ — type game.userId in browser console)")
        row_fuid.addWidget(lbl_fuid)
        row_fuid.addWidget(self.foundry_uid_edit)
        foundry_layout.addLayout(row_fuid)

        hint = QLabel(
            "The app connects directly to your Foundry server — no tunnel needed.\n"
            "The foundryvtt-bridge module must be installed and enabled in your world."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        foundry_layout.addWidget(hint)

        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_connection)
        foundry_layout.addWidget(test_btn)

        self.foundry_box.setVisible(False)
        root.addWidget(self.foundry_box)

        self.bridge_socket_radio.toggled.connect(self._on_bridge_mode_changed)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setDefault(True)
        self.save_btn.setMinimumWidth(120)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)

        self._prefill()

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_storage_mode_changed(self, local: bool) -> None:
        self.local_box.setVisible(local)
        self.api_box.setVisible(not local)

    def _on_bridge_mode_changed(self, socket_selected: bool) -> None:
        self.foundry_box.setVisible(socket_selected)
        self.adjustSize()

    def _browse(self) -> None:
        start = self.local_dir_edit.text() or _DEFAULT_DATA_DIR
        d = QFileDialog.getExistingDirectory(self, "Select Data Directory", start)
        if d:
            self.local_dir_edit.setText(d)

    def _prefill(self) -> None:
        # Storage
        mode = settings.get("storage_mode")
        if mode is None:
            env_api = os.getenv("USE_STORAGE_API_ONLY", "0").strip()
            mode = "api" if env_api not in ("", "0", "false", "False") else "local"
        if mode == "api":
            self.api_radio.setChecked(True)
            self._on_storage_mode_changed(False)

        self.local_dir_edit.setText(settings.get("local_data_dir") or os.getenv("LOCAL_DATA_DIR", ""))
        self.api_url_edit.setText(settings.get("storage_api_base") or os.getenv("STORAGE_API_BASE", ""))
        self.api_key_edit.setText(settings.get("storage_api_key") or os.getenv("STORAGE_API_KEY", ""))

        # Bridge
        bridge_mode = settings.get("bridge_mode", "local")
        if bridge_mode == "disabled":
            self.bridge_disabled_radio.setChecked(True)
        elif bridge_mode == "http_bridge":
            self.bridge_http_radio.setChecked(True)
        elif bridge_mode == "foundry_socket":
            self.bridge_socket_radio.setChecked(True)
            self._on_bridge_mode_changed(True)
        else:
            self.bridge_local_radio.setChecked(True)

        self.foundry_url_edit.setText(settings.get("foundry_url") or os.getenv("FOUNDRY_URL", ""))
        self.foundry_user_edit.setText(
            settings.get("foundry_username") or os.getenv("FOUNDRY_USERNAME", "Gamemaster")
        )
        self.foundry_pw_edit.setText(settings.get("foundry_password") or os.getenv("FOUNDRY_PASSWORD", ""))
        self.foundry_uid_edit.setText(settings.get("foundry_user_id") or os.getenv("FOUNDRY_USER_ID", ""))

    def _test_connection(self) -> None:
        from app.foundry_socket_client import FoundrySocketClient
        url = self.foundry_url_edit.text().strip()
        username = self.foundry_user_edit.text().strip()
        password = self.foundry_pw_edit.text().strip()
        if not url or not username:
            QMessageBox.warning(self, "Missing Fields", "Enter Foundry URL and username first.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Connection Test")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Testing connection to Foundry..."))
        output = QTextEdit()
        output.setReadOnly(True)
        output.setMinimumHeight(160)
        layout.addWidget(output)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        close_btn.setEnabled(False)
        layout.addWidget(close_btn)
        dlg.show()

        def run_test():
            client = FoundrySocketClient(url, username, password)
            result = client.test_connection()
            summary = result.summary()
            from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                output, "setPlainText",
                Qt.QueuedConnection,
                Q_ARG(str, summary),
            )
            QMetaObject.invokeMethod(
                close_btn, "setEnabled",
                Qt.QueuedConnection,
                Q_ARG(bool, True),
            )

        threading.Thread(target=run_test, daemon=True).start()
        dlg.exec_()

    def _on_save(self) -> None:
        # Validate storage
        if self.api_radio.isChecked() and not self.api_url_edit.text().strip():
            QMessageBox.warning(self, "Missing URL", "Please enter the API URL.")
            return

        # Validate bridge
        if self.bridge_socket_radio.isChecked():
            if not self.foundry_url_edit.text().strip():
                QMessageBox.warning(self, "Missing Foundry URL", "Please enter your Foundry server URL.")
                return
            if not self.foundry_user_edit.text().strip():
                QMessageBox.warning(self, "Missing Username", "Please enter your Foundry username.")
                return

        # Build update dict
        update: dict = {}

        if self.api_radio.isChecked():
            update["storage_mode"] = "api"
            update["storage_api_base"] = self.api_url_edit.text().strip()
            update["storage_api_key"] = self.api_key_edit.text().strip()
        else:
            update["storage_mode"] = "local"
            update["local_data_dir"] = self.local_dir_edit.text().strip()

        if self.bridge_disabled_radio.isChecked():
            update["bridge_mode"] = "disabled"
        elif self.bridge_http_radio.isChecked():
            update["bridge_mode"] = "http_bridge"
        elif self.bridge_socket_radio.isChecked():
            update["bridge_mode"] = "foundry_socket"
            update["foundry_url"] = self.foundry_url_edit.text().strip()
            update["foundry_username"] = self.foundry_user_edit.text().strip()
            update["foundry_password"] = self.foundry_pw_edit.text().strip()
            update["foundry_user_id"] = self.foundry_uid_edit.text().strip()
        else:
            update["bridge_mode"] = "local"

        settings.merge(update)
        self.accept()


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setFrameShadow(QFrame.Sunken)
    return sep
