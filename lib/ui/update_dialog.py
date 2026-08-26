# lib/ui/update_dialog.py
"""
The "a newer version exists" dialog: what changed, and how to get it.

This downloads a build; it does not install one. The app never executes what it
fetched -- the file lands in Downloads and the user runs it themselves. See
docs/auto-update.md for what a real in-app update would take, and why it is a
bigger job than it looks.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Optional

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from app import update_check
from app.version import __version__
from ui.release_notes_dialog import section_for


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def reveal(path: str) -> None:
    """Open the folder containing `path`, selecting it where the OS allows."""
    folder = os.path.dirname(path) or "."
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
            return
    except OSError:
        pass
    # Linux has no universal "select this file", so settle for the folder.
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


class UpdateDialog(QDialog):
    """What's new, plus a download button when the release has a build for us."""

    # The download runs on a worker thread; Qt widgets may only be touched on
    # the GUI thread, and a queued signal is the only safe way back.
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent=None, version: str = "", release: Optional[dict] = None):
        super().__init__(parent)
        self._version = (version or "").lstrip("vV")
        self._release = release
        self._asset = update_check.asset_for_platform(release)
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.setWindowTitle(f"Update Available — {self._version}")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(640, 560)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        heading = QLabel(
            f"Version {self._version} is available. You are running {__version__}."
        )
        heading.setWordWrap(True)
        root.addWidget(heading)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        text = section_for(self._version)
        # A build that predates this release has no section for it in its own
        # changelog, so fall back to what the release itself says.
        if not text or text.startswith("# Changelog"):
            text = (self._release or {}).get("body") or "No release notes available."
        notes.setMarkdown(text)
        root.addWidget(notes, stretch=1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setVisible(False)
        root.addWidget(self._bar)

        row = QHBoxLayout()
        self._download_btn = QPushButton()
        self._download_btn.clicked.connect(self._start_download)
        row.addWidget(self._download_btn)

        page_btn = QPushButton("Open Releases Page")
        page_btn.setToolTip("View this release on GitHub in your browser")
        page_btn.clicked.connect(self._open_page)
        row.addWidget(page_btn)
        row.addStretch()

        self._buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self._buttons.rejected.connect(self.reject)
        row.addWidget(self._buttons)
        root.addLayout(row)

        self.progress.connect(self._on_progress, Qt.QueuedConnection)
        self.finished_ok.connect(self._on_done, Qt.QueuedConnection)
        self.failed.connect(self._on_failed, Qt.QueuedConnection)

        self._configure_download_button()

    # ---- download -----------------------------------------------------------

    def _configure_download_button(self) -> None:
        if self._asset is None:
            self._download_btn.setEnabled(False)
            self._download_btn.setText("No build for this system")
            self._download_btn.setToolTip(
                "This release has no attached build matching this platform. "
                "The releases page has the source, and any builds that were "
                "published for other systems."
            )
            self._status.setText(
                "The release has no downloadable build for "
                f"{sys.platform}. Use the releases page."
            )
            return

        size = int(self._asset.get("size") or 0)
        label = self._asset.get("name", "the build")
        self._download_btn.setText(
            f"Download ({_human(size)})" if size else "Download"
        )
        self._download_btn.setToolTip(f"Download {label} to your Downloads folder")

    def _start_download(self) -> None:
        if self._thread is not None:          # already running: this is Cancel
            self._cancel.set()
            self._download_btn.setEnabled(False)
            self._status.setText("Cancelling…")
            return

        self._cancel.clear()
        self._bar.setVisible(True)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._download_btn.setText("Cancel")
        self._status.setText("Downloading…")

        target = update_check.downloads_dir()

        def run() -> None:
            try:
                path = update_check.download_asset(
                    self._asset,
                    target,
                    on_progress=lambda got, total: self.progress.emit(got, total),
                    cancelled=self._cancel.is_set,
                )
            except Exception as exc:
                self.failed.emit(str(exc))
                return
            if path is None:
                self.failed.emit("")          # cancelled, not an error
            else:
                self.finished_ok.emit(path)

        self._thread = threading.Thread(target=run, name="update-download", daemon=True)
        self._thread.start()

    def _on_progress(self, received: int, total: int) -> None:
        if total > 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(int(received * 100 / total))
            self._status.setText(f"Downloading… {_human(received)} of {_human(total)}")
        else:
            # No Content-Length: show motion rather than a stuck bar at zero.
            self._bar.setRange(0, 0)
            self._status.setText(f"Downloading… {_human(received)}")

    def _on_done(self, path: str) -> None:
        self._thread = None
        self._bar.setVisible(False)
        self._download_btn.setText("Show in Folder")
        self._download_btn.setEnabled(True)
        try:
            self._download_btn.clicked.disconnect()
        except TypeError:
            pass
        self._download_btn.clicked.connect(lambda: reveal(path))
        self._status.setText(
            f"Saved to {path}\n"
            "Unpack it and run it from there — nothing was installed or replaced, "
            "and your settings and data are untouched."
        )

    def _on_failed(self, message: str) -> None:
        self._thread = None
        self._bar.setVisible(False)
        self._download_btn.setText("Download")
        self._download_btn.setEnabled(True)
        self._status.setText(
            f"Download failed: {message}" if message else "Download cancelled."
        )

    def _open_page(self) -> None:
        url = (self._release or {}).get("html_url") or update_check.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def reject(self) -> None:
        self._cancel.set()
        super().reject()
