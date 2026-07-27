# lib/ui/pc_groups_dialog.py
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QInputDialog, QLineEdit,
)


def prompt_for_group(app, title: str, parent=None):
    """Ask for a group name; return (name, key), or None if cancelled.

    Confirms before reusing the key of an existing group.
    """
    name, ok = QInputDialog.getText(parent, title, "Group name:", QLineEdit.Normal)
    if not ok or not name.strip():
        return None
    key = app._pc_group_key(name)
    try:
        existing = {k for _, k in app.list_pc_groups()}
    except Exception:
        existing = set()
    if key in existing:
        resp = QMessageBox.question(
            parent, "Overwrite Group",
            f"A group named '{app._pc_group_display(key)}' already exists.\n"
            "Overwrite it?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return None
    return name, key


def create_new_pc_group(app, parent=None) -> bool:
    """Name a new group, then build its roster from scratch in the editor.

    Returns True if a group was saved. Shared by the PC Groups dialog and the
    File → PC Groups → New Group… menu entry.
    """
    from ui.update_characters import UpdateCharactersWindow

    prompt = prompt_for_group(app, "New PC Group", parent)
    if not prompt:
        return False
    _name, key = prompt
    editor = UpdateCharactersWindow(app, group_key=key, new_group=True)
    return editor.exec_() == QDialog.Accepted


class PCGroupsDialog(QDialog):
    """Manage saved PC groups: load, save the current party, rename, delete.

    Talks to the Application via the parent window's group methods
    (list_pc_groups / save_pc_group / load_pc_group / delete_pc_group).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = parent
        self.setWindowTitle("PC Groups")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Saved PC groups:"))

        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QListWidget.SingleSelection)
        self.group_list.itemDoubleClicked.connect(lambda _: self.on_load())
        layout.addWidget(self.group_list)

        # Load / row of primary actions
        top_row = QHBoxLayout()
        self.load_btn = QPushButton("Load Group")
        self.load_btn.clicked.connect(self.on_load)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.on_delete)
        top_row.addWidget(self.load_btn)
        top_row.addWidget(self.delete_btn)
        layout.addLayout(top_row)

        # Build a group from scratch, or snapshot whoever is in the table now.
        self.new_btn = QPushButton("New Group…")
        self.new_btn.clicked.connect(self.on_new)
        layout.addWidget(self.new_btn)

        self.save_btn = QPushButton("Save Current PCs as Group…")
        self.save_btn.clicked.connect(self.on_save)
        layout.addWidget(self.save_btn)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        close_row.addWidget(self.close_btn)
        layout.addLayout(close_row)

        self._populate()

    def _populate(self):
        self.group_list.clear()
        try:
            groups = self.app.list_pc_groups()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to list groups:\n{e}")
            return
        for display, key in groups:
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, key)
            self.group_list.addItem(item)
        if self.group_list.count() == 0:
            item = QListWidgetItem("(no saved groups yet)")
            item.setFlags(Qt.NoItemFlags)
            self.group_list.addItem(item)

    def _selected_key(self):
        item = self.group_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    def on_load(self):
        key = self._selected_key()
        if not key:
            QMessageBox.information(self, "No Selection", "Select a group to load.")
            return
        try:
            self.app.load_pc_group(key)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load group:\n{e}")
            return
        if hasattr(self.app, "show_status_message"):
            self.app.show_status_message(f"Loaded PC group: {self.app._pc_group_display(key)}")
        self.accept()

    def on_new(self):
        """Create a group from scratch: name it, then fill in brand-new PCs."""
        if create_new_pc_group(self.app, self):
            self.accept()
        else:
            self._populate()

    def on_save(self):
        prompt = prompt_for_group(self.app, "Save PC Group", self)
        if not prompt:
            return
        name, _key = prompt
        try:
            self.app.save_pc_group(name)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save group:\n{e}")
            return
        self._populate()

    def on_delete(self):
        key = self._selected_key()
        if not key:
            QMessageBox.information(self, "No Selection", "Select a group to delete.")
            return
        resp = QMessageBox.question(
            self, "Delete Group",
            f"Delete PC group '{self.app._pc_group_display(key)}'?\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        try:
            self.app.delete_pc_group(key)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to delete group:\n{e}")
            return
        self._populate()
