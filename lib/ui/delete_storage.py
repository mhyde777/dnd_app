# lib/ui/delete_storage.py
from __future__ import annotations
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QMessageBox
)

from .storage_status import STATUS_PATH  # reuse same status file


class DeleteStorageWindow(QDialog):
    """
    Select and delete encounters from the Storage API.
    Also removes them from the local status file if present.
    """
    def __init__(self, storage_api, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Delete Encounters")
        self.storage_api = storage_api

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Select encounters to delete:"))

        self.listw = QListWidget()
        self.listw.setSelectionMode(QListWidget.MultiSelection)
        v.addWidget(self.listw)

        row = QHBoxLayout()
        self.btn_delete = QPushButton("Delete Selected")
        self.btn_cancel = QPushButton("Cancel")
        row.addWidget(self.btn_delete)
        row.addWidget(self.btn_cancel)
        v.addLayout(row)

        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_cancel.clicked.connect(self.reject)

        self._populate()

    def _populate(self):
        try:
            if not self.storage_api:
                raise RuntimeError("Storage API not configured.")
            items = self.storage_api.list()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to list encounters:\n{e}")
            self.reject()
            return

        keys = [
            k for k in items
            if isinstance(k, str)
            and k.endswith(".json")
            and k not in ("players.json", "last_state.json")
        ]
        keys.sort(key=str.lower)

        if not keys:
            self.listw.addItem(QListWidgetItem("(No encounters found)"))
            self.listw.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return

        for key in keys:
            display = key.replace("_", " ").replace(".json", "")
            it = QListWidgetItem(display)
            it.setData(Qt.UserRole, key)
            self.listw.addItem(it)

    def _on_delete(self):
        selected = [it for it in self.listw.selectedItems() if it.data(Qt.UserRole)]
        if not selected:
            QMessageBox.information(self, "None Selected", "Please select at least one encounter.")
            return

        names = [it.data(Qt.UserRole) for it in selected]
        pretty = "\n".join(names)
        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete these encounters?\n\n{pretty}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        # Perform deletions
        errors = []
        for key in names:
            try:
                self.storage_api.delete(key)
            except Exception as e:
                errors.append(f"{key}: {e}")

        # Clean from local status file if present
        try:
            import json
            if os.path.exists(STATUS_PATH):
                with open(STATUS_PATH, "r") as f:
                    status = json.load(f) or {}
                for key in names:
                    status.pop(key, None)
                with open(STATUS_PATH, "w") as f:
                    json.dump(status, f, ensure_ascii=False, indent=2)
        except Exception:
            # non-fatal
            pass

        if errors:
            QMessageBox.warning(self, "Some Failed", "Errors:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Deleted", "Selected encounters were deleted.")
        self.accept()

