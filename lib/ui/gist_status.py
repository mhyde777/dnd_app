# ui/gist_status.py
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QCheckBox, QPushButton, QMessageBox
)
from PyQt5.QtCore import Qt
from app.gist_utils import list_gists
import os, json

STATUS_PATH = os.path.expanduser("~/.dnd_tracker_config/gist_status.json")

class GistStatusWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gist Status Manager")
        self.resize(400, 500)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.status_data = self.load_status_data()
        self.checkbox_items = {}

        self.populate_gists()
        self.save_button = QPushButton("Save Changes")
        self.save_button.clicked.connect(self.save_statuses)
        self.layout.addWidget(self.save_button)

    def load_status_data(self):
        if os.path.exists(STATUS_PATH):
            with open(STATUS_PATH, "r") as f:
                return json.load(f)
        return {}

    def populate_gists(self):
        try:
            gists = list_gists()
            for gist in gists:
                for filename in gist.get("files", {}):
                    if filename.endswith(".json") and filename not in ["players.json", "last_state.json"]:
                        checkbox = QCheckBox(filename.replace("_", " "))
                        checkbox.setChecked(self.status_data.get(filename, True))  # Default to active
                        self.checkbox_items[filename] = checkbox
                        self.layout.addWidget(checkbox)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load Gists: {e}")

    def save_statuses(self):
        try:
            for filename, checkbox in self.checkbox_items.items():
                self.status_data[filename] = checkbox.isChecked()
            os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
            with open(STATUS_PATH, "w") as f:
                json.dump(self.status_data, f, indent=4)
            QMessageBox.information(self, "Success", "Statuses updated!")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save statuses: {e}")

