# lib/ui/versions_dialog.py
"""
Switch between the versions installed side by side, or delete one.

Updating keeps the previous build rather than overwriting it (see
install_layout.py), which means going back is the same operation as going
forward: point `current` at a different directory and restart. The launcher
already does this by itself when a new version fails to start; this is the
same thing for a version that starts and is merely worse.
"""
from __future__ import annotations

import os
import shutil

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app import install_layout, update_install
from app.version import __version__


def _directory_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


class VersionsDialog(QDialog):
    """The installed versions, and which one starts next."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracker = parent
        self._layout_info = install_layout.detect()

        self.setWindowTitle("Installed Versions")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(520, 380)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self._intro = QLabel()
        self._intro.setWordWrap(True)
        root.addWidget(self._intro)

        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        root.addWidget(self._list, stretch=1)

        row = QHBoxLayout()
        self._switch = QPushButton("Switch and Restart")
        self._switch.setObjectName("primaryButton")
        self._switch.clicked.connect(self._on_switch)
        row.addWidget(self._switch)

        self._delete = QPushButton("Delete")
        self._delete.setToolTip("Remove this version from disk")
        self._delete.clicked.connect(self._on_delete)
        row.addWidget(self._delete)
        row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        root.addLayout(row)

        self._reload()

    # ---- state --------------------------------------------------------------

    def _reload(self) -> None:
        self._list.clear()

        if self._layout_info is None:
            self._intro.setText(
                f"You are running {__version__} from a source checkout or an "
                "install that predates side-by-side versions, so there is "
                "nothing to switch between."
            )
            self._switch.setEnabled(False)
            self._delete.setEnabled(False)
            return

        layout = self._layout_info
        running = layout.version
        selected = install_layout.read_current(layout) or running
        versions = sorted(
            layout.installed_versions(),
            key=lambda v: [int(p) for p in v.split(".") if p.isdigit()],
            reverse=True,
        )

        total = 0
        for version in versions:
            size = _directory_size(layout.version_dir(version))
            total += size
            marks = []
            if version == running:
                marks.append("running now")
            if version == selected and version != running:
                marks.append("starts next")
            suffix = f"  —  {', '.join(marks)}" if marks else ""
            item = QListWidgetItem(f"{version}   ({_human(size)}){suffix}")
            item.setData(Qt.UserRole, version)
            self._list.addItem(item)
            if version == selected:
                self._list.setCurrentItem(item)

        self._intro.setText(
            f"Updating installs alongside the previous version instead of "
            f"replacing it, so you can go back. {len(versions)} installed, "
            f"{_human(total)} in total. Older ones are removed automatically "
            f"once there are more than three."
        )
        self._sync_buttons()

    def _selected_version(self):
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _sync_buttons(self) -> None:
        if self._layout_info is None:
            return
        version = self._selected_version()
        running = self._layout_info.version
        selected = install_layout.read_current(self._layout_info) or running

        self._switch.setEnabled(bool(version) and version != selected)
        # Never offer to delete the build that is running, or the one queued to
        # run next -- either would leave the install unable to start.
        self._delete.setEnabled(
            bool(version) and version != running and version != selected
        )

    # ---- actions ------------------------------------------------------------

    def _on_switch(self) -> None:
        version = self._selected_version()
        if not version or self._layout_info is None:
            return

        direction = "Reverting to" if version < self._layout_info.version else "Switching to"
        answer = QMessageBox.question(
            self,
            "Switch Version",
            f"{direction} {version}.\n\n"
            "Restart now? Your combat is saved first, and nothing is deleted — "
            f"you can come back to {self._layout_info.version} the same way.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            install_layout.write_current(self._layout_info, version)
        except OSError as exc:
            QMessageBox.warning(
                self, "Switch Failed", f"Could not select {version}:\n{exc}"
            )
            return

        tracker = self._tracker
        if tracker is not None and hasattr(tracker, "restart_app"):
            self.accept()
            tracker.restart_app()
        else:
            self._reload()

    def _on_delete(self) -> None:
        version = self._selected_version()
        if not version or self._layout_info is None:
            return
        path = self._layout_info.version_dir(version)
        answer = QMessageBox.question(
            self,
            "Delete Version",
            f"Delete {version} from disk?\n\nIt can be reinstalled by "
            "downloading that release again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        shutil.rmtree(path, ignore_errors=True)
        self._reload()
