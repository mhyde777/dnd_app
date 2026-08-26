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
import threading
from datetime import datetime, timezone

from PyQt5.QtCore import Qt, pyqtSignal
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

from app import install_layout, update_check, update_install
from app.version import __version__


_ON_DISK = Qt.UserRole + 1
_AVAILABLE = Qt.UserRole + 2


def _version_key(version: str) -> tuple:
    parts = [int(p) if p.isdigit() else 0 for p in version.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))[:4]


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
    """Every version you can run: on disk, previously run, or published."""

    # Releases are fetched on a worker thread and merged in when they arrive,
    # so the dialog opens instantly and works offline with whatever is local.
    releases_fetched = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._releases = {}          # version -> release payload
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

        self.releases_fetched.connect(self._on_releases, Qt.QueuedConnection)
        self._reload()
        self._fetch_releases()

    # ---- published releases -------------------------------------------------

    def _fetch_releases(self) -> None:
        if self._layout_info is None:
            return

        def run():
            try:
                releases = update_check.fetch_releases()
            except Exception:
                releases = []
            self.releases_fetched.emit(releases)

        threading.Thread(target=run, name="versions-fetch", daemon=True).start()

    def _on_releases(self, releases) -> None:
        self._releases = {
            update_check.version_of(release): release for release in (releases or [])
        }
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
            due = install_layout.retire_at(version)
            if due is not None:
                remaining = due - datetime.now(timezone.utc)
                minutes = max(0, int(remaining.total_seconds() // 60))
                marks.append(
                    f"kept {minutes} more min in case {running} misbehaves"
                    if minutes else "due to be removed"
                )
            suffix = f"  —  {', '.join(marks)}" if marks else ""
            item = QListWidgetItem(f"{version}   ({_human(size)}){suffix}")
            item.setData(Qt.UserRole, version)
            item.setData(_ON_DISK, True)
            item.setData(_AVAILABLE, True)
            self._list.addItem(item)
            if version == selected:
                self._list.setCurrentItem(item)

        # Everything else you could run: versions this machine used before, and
        # published releases it never did. Both are still downloadable, so both
        # are somewhere to go back to -- just not instantly.
        last_used = {
            entry.get("version"): (entry.get("last_run") or "")[:10]
            for entry in install_layout.version_history()
            if entry.get("version")
        }
        elsewhere = sorted(
            set(last_used) | set(self._releases),
            key=_version_key,
            reverse=True,
        )
        for version in elsewhere:
            if version in versions:
                continue
            release = self._releases.get(version)
            # A release with no build for this platform cannot be offered; the
            # 0.2.0 release went out with no assets at all, for instance.
            downloadable = release is None or bool(
                update_check.asset_for_platform(release)
            )
            if version in last_used:
                note = f"not installed, last used {last_used[version]}"
            else:
                note = "available to download"
            if not downloadable:
                note = "no build for this system"

            item = QListWidgetItem(f"{version}   ({note})")
            item.setData(Qt.UserRole, version)
            item.setData(_ON_DISK, False)
            item.setData(_AVAILABLE, downloadable)
            item.setForeground(Qt.gray)
            self._list.addItem(item)

        keep = install_layout.keep_versions()
        pending = "" if self._releases else " Checking for other released versions…"
        self._intro.setText(
            f"{len(versions)} version{'s' if len(versions) != 1 else ''} on disk, "
            f"{_human(total)} in total; only the newest {keep} "
            f"{'is' if keep == 1 else 'are'} kept once a new one has proved "
            f"itself. Greyed-out versions are not installed — selecting one "
            f"downloads it from its release." + pending
        )
        self._sync_buttons()

    def _selected_version(self):
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _selected_on_disk(self) -> bool:
        item = self._list.currentItem()
        return bool(item and item.data(_ON_DISK))

    def _sync_buttons(self) -> None:
        if self._layout_info is None:
            return
        version = self._selected_version()
        on_disk = self._selected_on_disk()
        running = self._layout_info.version
        selected = install_layout.read_current(self._layout_info) or running

        item = self._list.currentItem()
        available = bool(item and item.data(_AVAILABLE))
        if version and not on_disk:
            self._switch.setText("Download and Switch")
            self._switch.setEnabled(available)
        else:
            self._switch.setText("Switch and Restart")
            self._switch.setEnabled(bool(version) and version != selected)
        # Never offer to delete the build that is running, or the one queued to
        # run next -- either would leave the install unable to start.
        self._delete.setEnabled(
            bool(version) and on_disk and version != running and version != selected
        )

    # ---- actions ------------------------------------------------------------

    def _on_switch(self) -> None:
        version = self._selected_version()
        if not version or self._layout_info is None:
            return
        if not self._selected_on_disk():
            self._download_and_switch(version)
            return

        older = _version_key(version) < _version_key(self._layout_info.version)
        direction = "Reverting to" if older else "Switching to"
        # No compatibility metadata exists yet, so this says what is true rather
        # than pretending to know: newer versions can write settings and saves
        # an older one has never seen. A per-release "reads data from" floor
        # would let this be specific instead of general.
        caution = (
            "\n\nGoing back more than a version or two can matter: settings and "
            "saved encounters written by a newer version may not be understood "
            "by an older one. Your files are not deleted either way."
            if older else ""
        )
        answer = QMessageBox.question(
            self,
            "Switch Version",
            f"{direction} {version}.{caution}\n\n"
            "Restart now? Your combat is saved first, and nothing is deleted — "
            f"you can come back to {self._layout_info.version} the same way.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            install_layout.write_current(self._layout_info, version)
            # Chosen to run again, so it is no longer on its way out.
            install_layout.cancel_retirement(version)
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

    def _download_and_switch(self, version: str) -> None:
        """Reinstall a version that was pruned, from its release.

        The whole reason old builds can be deleted at all: the release they
        came from is still there, so "gone from disk" is not "gone".
        """
        answer = QMessageBox.question(
            self,
            "Download Version",
            f"{version} is not installed. Download it from its release and "
            "switch to it?\n\nYour combat is saved first. Settings and saved "
            "encounters written by a newer version may not be understood by an "
            "older one, though nothing is deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        release = update_check.fetch_release_by_tag(version)
        if release is None:
            QMessageBox.warning(
                self, "Not Available",
                f"There is no published release for {version} any more, so it "
                "cannot be downloaded. Only versions still on disk can be used.",
            )
            return

        from ui.update_dialog import UpdateDialog

        # The update dialog already does download, verify, install and restart.
        # Reinstalling an older version is the same work in the other
        # direction, so it runs through the same code rather than a second copy
        # of it that would drift.
        self.accept()
        UpdateDialog(self._tracker, version=version, release=release).exec_()

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
