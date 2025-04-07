from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QDialogButtonBox
)
from app.gist_utils import list_gists, delete_gist, load_gist_index, save_gist_index

class DeleteGistWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Delete Gists")
        self.resize(500, 400)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.gist_list = QListWidget()
        self.gist_list.setSelectionMode(QListWidget.MultiSelection)
        self.layout.addWidget(self.gist_list)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.confirm_and_delete)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

        self.gist_data = []  # Store (description, filename, gist_id)
        self.populate_list()

    def populate_list(self):
        try:
            gists = list_gists()
            for gist in gists:
                gist_id = gist["id"]
                description = gist.get("description", "No Description")
                filenames = list(gist["files"].keys())
                for filename in filenames:
                    if filename.endswith(".json"):
                        item_text = f"{filename.replace('_', ' ')} — {description}"
                        item = QListWidgetItem(item_text)
                        item.setData(256, (filename, gist_id))  # Use Qt.UserRole = 256
                        self.gist_list.addItem(item)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load gists:\n{e}")
            self.reject()

    def confirm_and_delete(self):
        selected_items = self.gist_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a gist to delete.")
            return

        confirm = QMessageBox.question(
            self,
            "Are You Sure?",
            f"Are you sure you want to delete {len(selected_items)} selected gist(s)?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        index = load_gist_index()

        for item in selected_items:
            filename, gist_id = item.data(256)
            try:
                delete_gist(gist_id)
                if filename in index:
                    del index[filename]
                self.gist_list.takeItem(self.gist_list.row(item))
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete {filename}:\n{e}")

        save_gist_index(index)
        QMessageBox.information(self, "Done", "Selected gists have been deleted.")
        self.accept()

