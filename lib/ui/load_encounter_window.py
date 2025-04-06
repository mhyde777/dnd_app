from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton, QMessageBox
from app.gist_utils import list_gists

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
            gists = list_gists()
            for gist in gists:
                for filename, filedata in gist.get("files", {}).items():
                    if filename.endswith(".json"):
                        display_name = f"{filename} ({gist['description']})" if gist['description'] else filename
                        self.gist_list.addItem(f"{display_name}|||{filedata['raw_url']}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load Gists: {e}")
            self.reject()

    def accept_selection(self):
        selected = self.gist_list.currentItem()
        if selected:
            text = selected.text()
            parts = text.split("|||")
            if len(parts) == 2:
                self.selected_file = parts[1]  # the raw_url
                self.accept()
        else:
            QMessageBox.warning(self, "No Selection", "Please select a Gist to load.")
