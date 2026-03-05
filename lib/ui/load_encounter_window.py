# lib/ui/load_encounter_window.py
from __future__ import annotations
import json, os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QHBoxLayout
)

from app.config import get_config_path

STATUS_PATH = get_config_path("encounter_status.json")

class LoadEncounterWindow(QDialog):
    """
    Storage-backed 'Load/Merge Encounter' picker.

    Accepts a storage object (StorageAPI or LocalStorage) from the caller
    so it uses the same backend as the rest of the app.
    """

    def __init__(self, parent=None, storage=None):
        super().__init__(parent)
        self.setWindowTitle("Load/Merge Encounter")
        self.selected_file = None
        self.storage_api = storage

        layout = QVBoxLayout(self)

        self.info_label = QLabel("Select an Encounter to load:")
        layout.addWidget(self.info_label)

        self.encounter_list = QListWidget()
        self.encounter_list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self.encounter_list)

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
                raise RuntimeError(
                    "Storage is not configured.\n\nGo to File → Settings to configure storage."
                )

            encounter_status = {}
            if os.path.exists(STATUS_PATH):
                with open(STATUS_PATH, "r") as f:
                    encounter_status = json.load(f)

            items = self.storage_api.list()
            for filename in items:
                if (
                    isinstance(filename, str)
                    and filename.endswith(".json")
                    and filename not in ("players.json", "last_state.json")
                    and encounter_status.get(filename, True)
                ):
                    display = filename.replace("_", " ").replace(".json", "")
                    item = QListWidgetItem(display)
                    item.setData(Qt.UserRole, filename)
                    self.encounter_list.addItem(item)

            if self.encounter_list.count() == 0:
                self.info_label.setText("No encounters found.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load encounters: {e}")
            self.reject()

    def on_load_clicked(self):
        item = self.encounter_list.currentItem()
        if not item:
            QMessageBox.information(self, "No Selection", "Please select an Encounter.")
            return
        self.selected_file = item.data(Qt.UserRole)
        self.accept()
