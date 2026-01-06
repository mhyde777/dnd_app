# lib/ui/manage_images.py
from __future__ import annotations
import mimetypes
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QMessageBox, QFileDialog, QInputDialog, QLineEdit
)


class ManageImagesWindow(QDialog):
    def __init__(self, storage_api, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Images")
        self.storage_api = storage_api
        self.updated = False

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Upload, replace, or delete images stored in the Storage API."))

        self.listw = QListWidget()
        self.listw.setSelectionMode(QListWidget.MultiSelection)
        v.addWidget(self.listw)

        actions_row = QHBoxLayout()
        self.btn_upload = QPushButton("Upload New")
        self.btn_replace = QPushButton("Replace Selected")
        self.btn_delete = QPushButton("Delete Selected")
        self.btn_refresh = QPushButton("Refresh")
        self.btn_close = QPushButton("Close")
        actions_row.addWidget(self.btn_upload)
        actions_row.addWidget(self.btn_replace)
        actions_row.addWidget(self.btn_delete)
        actions_row.addWidget(self.btn_refresh)
        actions_row.addWidget(self.btn_close)
        v.addLayout(actions_row)

        self.btn_upload.clicked.connect(self._on_upload)
        self.btn_replace.clicked.connect(self._on_replace)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_refresh.clicked.connect(self._populate)
        self.btn_close.clicked.connect(self.accept)

        self._populate()

    def _populate(self):
        self.listw.clear()
        try:
            if not self.storage_api:
                raise RuntimeError("Storage API not configured.")
            items = self.storage_api.list_images()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to list images:\n{e}")
            return

        keys = [k for k in items if isinstance(k, str)]
        keys.sort(key=str.lower)

        if not keys:
            self.listw.addItem(QListWidgetItem("(No images found)"))
            self.listw.setEnabled(False)
            self.btn_replace.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return

        self.listw.setEnabled(True)
        self.btn_replace.setEnabled(True)
        self.btn_delete.setEnabled(True)
        for key in keys:
            it = QListWidgetItem(key)
            it.setData(Qt.UserRole, key)
            self.listw.addItem(it)

    def _guess_content_type(self, path: str) -> str:
        guess, _ = mimetypes.guess_type(path)
        return guess or "application/octet-stream"

    def _read_file_bytes(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def _prompt_key(self, default_key: str) -> str:
        key, ok = QInputDialog.getText(
            self, "Image Key", "Enter image filename:", QLineEdit.Normal, default_key
        )
        if not ok:
            return ""
        return key.strip()

    def _on_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg *.gif);;All Files (*)",
        )
        if not path:
            return

        default_key = os.path.basename(path)
        key = self._prompt_key(default_key)
        if not key:
            return

        if not os.path.splitext(key)[1]:
            _, ext = os.path.splitext(default_key)
            if ext:
                key = f"{key}{ext}"

        try:
            data = self._read_file_bytes(path)
            content_type = self._guess_content_type(path)
            self.storage_api.put_image_bytes(key, data, content_type=content_type)
            self.updated = True
            QMessageBox.information(self, "Uploaded", f"Uploaded image as:\n{key}")
            self._populate()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to upload image:\n{e}")

    def _on_replace(self):
        selected = [it for it in self.listw.selectedItems() if it.data(Qt.UserRole)]
        if not selected:
            QMessageBox.information(self, "None Selected", "Please select an image to replace.")
            return
        if len(selected) > 1:
            QMessageBox.information(self, "Too Many", "Please select only one image to replace.")
            return

        key = selected[0].data(Qt.UserRole)
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Replace {key}",
            "",
            "Images (*.png *.jpg *.jpeg *.gif);;All Files (*)",
        )
        if not path:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Replace",
            f"Replace existing image '{key}' with the selected file?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            data = self._read_file_bytes(path)
            content_type = self._guess_content_type(path)
            self.storage_api.put_image_bytes(key, data, content_type=content_type)
            self.updated = True
            QMessageBox.information(self, "Replaced", f"Replaced image:\n{key}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to replace image:\n{e}")

    def _on_delete(self):
        selected = [it for it in self.listw.selectedItems() if it.data(Qt.UserRole)]
        if not selected:
            QMessageBox.information(self, "None Selected", "Please select at least one image.")
            return

        names = [it.data(Qt.UserRole) for it in selected]
        pretty = "\n".join(names)
        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete these images?\n\n{pretty}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        errors = []
        for key in names:
            try:
                self.storage_api.delete_image(key)
            except Exception as e:
                errors.append(f"{key}: {e}")

        if errors:
            QMessageBox.warning(self, "Some Failed", "Errors:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Deleted", "Selected images were deleted.")
            self.updated = True
            self._populate()
