# lib/ui/storage_status.py
from __future__ import annotations
import json, os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QMessageBox
)

STATUS_PATH = os.path.expanduser("~/.dnd_tracker_config/gist_status.json")


class StorageStatusWindow(QDialog):
    """
    Toggle active/inactive for encounters stored in the Storage API.
    We write flags back to ~/.dnd_tracker_config/gist_status.json.
    """
    def __init__(self, storage_api, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Encounters (Active / Inactive)")
        self.storage_api = storage_api
        self.status = self._load_status()

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Check encounters to mark them ACTIVE:"))

        self.listw = QListWidget()
        self.listw.setSelectionMode(QListWidget.NoSelection)
        v.addWidget(self.listw)

        row = QHBoxLayout()
        self.btn_save = QPushButton("Save")
        self.btn_cancel = QPushButton("Cancel")
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_cancel)
        v.addLayout(row)

        self.btn_save.clicked.connect(self._on_save)
        self.btn_cancel.clicked.connect(self.reject)

        self._populate()

    # -------- internals --------
    def _load_status(self) -> dict:
        try:
            os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
            if os.path.exists(STATUS_PATH):
                with open(STATUS_PATH, "r") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_status(self):
        try:
            os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
            with open(STATUS_PATH, "w") as f:
                json.dump(self.status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save status file:\n{e}")

    def _populate(self):
        try:
            if not self.storage_api:
                raise RuntimeError("Storage API not configured.")
            items = self.storage_api.list()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to list encounters:\n{e}")
            self.reject()
            return

        # Filter encounters (exclude system files)
        keys = [
            k for k in items
            if isinstance(k, str)
            and k.endswith(".json")
            and k not in ("players.json", "last_state.json")
        ]
        keys.sort(key=str.lower)

        for key in keys:
            display = key.replace("_", " ").replace(".json", "")
            it = QListWidgetItem(display)
            it.setData(Qt.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            # Checked = ACTIVE (default active if not present)
            is_active = bool(self.status.get(key, True))
            it.setCheckState(Qt.Checked if is_active else Qt.Unchecked)
            self.listw.addItem(it)

        if self.listw.count() == 0:
            self.listw.addItem(QListWidgetItem("(No encounters found)"))

    def _on_save(self):
        # Read back check states into self.status
        for i in range(self.listw.count()):
            it = self.listw.item(i)
            key = it.data(Qt.UserRole)
            if not key:  # skip placeholder row
                continue
            self.status[key] = (it.checkState() == Qt.Checked)
        self._save_status()
        self.accept()

