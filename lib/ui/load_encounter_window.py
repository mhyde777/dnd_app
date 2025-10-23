# lib/ui/load_encounter_window.py
from __future__ import annotations
import json, os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QHBoxLayout
)

from app.config import get_storage_api_base, use_storage_api_only
from app.storage_api import StorageAPI

STATUS_PATH = os.path.expanduser("~/.dnd_tracker_config/gist_status.json")


class LoadEncounterWindow(QDialog):
    """
    Storage-backed 'Load/Merge Encounter' picker.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load/Merge Encounter")
        self.selected_file = None

        self.storage_api = None
        if use_storage_api_only():
            base = get_storage_api_base()
            if base:
                self.storage_api = StorageAPI(base)

        layout = QVBoxLayout(self)

        self.info_label = QLabel("Select an Encounter to load:")
        layout.addWidget(self.info_label)

        self.gist_list = QListWidget()
        self.gist_list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self.gist_list)

        # Buttons
        row = QHBoxLayout()
        self.load_btn = QPushButton("Load")
        self.cancel_btn = QPushButton("Cancel")
        row.addWidget(self.load_btn)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)

        self.load_btn.clicked.connect(self.on_load_clicked)
        self.cancel_btn.clicked.connect(self.reject)

        self._populate()

    def _populate(self):
        try:
            if not self.storage_api:
                raise RuntimeError("Storage API not configured.")

            # reuse existing status file for active/inactive toggles
            gist_status = {}
            if os.path.exists(STATUS_PATH):
                with open(STATUS_PATH, "r") as f:
                    gist_status = json.load(f)

            items = self.storage_api.list()
            for filename in items:
                if (
                    isinstance(filename, str)
                    and filename.endswith(".json")
                    and filename not in ("players.json", "last_state.json")
                    and gist_status.get(filename, True)  # default active
                ):
                    display = filename.replace("_", " ").replace(".json", "")
                    item = QListWidgetItem(display)
                    item.setData(Qt.UserRole, filename)  # store Storage key
                    self.gist_list.addItem(item)

            if self.gist_list.count() == 0:
                self.info_label.setText("No encounters found in Storage.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load encounters: {e}")
            self.reject()

    def on_load_clicked(self):
        item = self.gist_list.currentItem()
        if not item:
            QMessageBox.information(self, "No Selection", "Please select an Encounter.")
            return
        self.selected_file = item.data(Qt.UserRole)  # Storage key
        self.accept()
