from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QMessageBox
from PyQt5.QtCore import Qt
from app.gist_utils import list_gists
import os, json

STATUS_PATH = os.path.expanduser("~/.dnd_tracker_config/gist_status.json")

class LoadEncounterWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Encounter from Gist")
        self.selected_file = None

        layout = QVBoxLayout(self)

        self.info_label = QLabel("Select a Gist to load:")
        layout.addWidget(self.info_label)

        self.gist_list = QListWidget()
        layout.addWidget(self.gist_list)

        self.load_button = QPushButton("Load Encounter")
        self.load_button.clicked.connect(self.accept_selection)
        layout.addWidget(self.load_button)

        self.populate_gist_list()

    def populate_gist_list(self):
        try:
            # Load status JSON
            if os.path.exists(STATUS_PATH):
                with open(STATUS_PATH, "r") as f:
                    gist_status = json.load(f)
            else:
                gist_status = {}

            gists = list_gists()
            for gist in gists:
                for filename, filedata in gist.get("files", {}).items():
                    if (
                        filename.endswith(".json")
                        and filename not in ["players.json", "last_state.json"]
                        and gist_status.get(filename, True)  # Only include if marked active (or default to active)
                    ):
                        display_name = filename.replace("_", " ").replace(".json", "")
                        item = QListWidgetItem(display_name)
                        item.setData(Qt.UserRole, filedata["raw_url"])
                        self.gist_list.addItem(item)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load Gists: {e}")
            self.reject()

    def accept_selection(self):
        selected = self.gist_list.currentItem()
        if selected:
            self.selected_file = selected.data(Qt.UserRole)  # Retrieve the raw_url
            self.accept()
        else:
            QMessageBox.warning(self, "No Selection", "Please select a Gist to load.")
