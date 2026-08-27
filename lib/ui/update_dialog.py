# lib/ui/update_dialog.py
"""
The "a newer version exists" dialog: what changed, and one button to take it.

Where the installation supports it (see install_layout.py) the button runs the
whole thing -- download, verify, install beside the running version, restart.
Where it doesn't, it degrades to downloading the build to Downloads and saying
why it can't do more, rather than hiding the update behind a disabled control.

The install never writes over the running version; it adds a new directory and
repoints `current`. docs/auto-update.md explains why that distinction is the
whole ballgame.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Optional

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from app import install_layout, update_check, update_install
from app.version import __version__
from ui.release_notes_dialog import section_for


def _human(size: float) -> str:
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
    """What's new, and the shortest route to running it."""

    # Every step below runs on a worker thread; Qt widgets may only be touched
    # on the GUI thread, so results come back as queued signals.
    progress = pyqtSignal(int, int, str)
    downloaded = pyqtSignal(str)
    installed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent=None, version: str = "", release: Optional[dict] = None):
        super().__init__(parent)
        self._tracker = parent
        self._version = (version or "").lstrip("vV")
        self._release = release or {}
        self._asset = update_check.asset_for_platform(release)
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._can_install, self._why_not = install_layout.can_self_update()

        self.setWindowTitle(f"Update Available — {self._version}")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(660, 580)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        heading = QLabel(
            f"Version {self._version} is available. You are running {__version__}."
        )
        heading.setWordWrap(True)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        root.addWidget(heading)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        text = section_for(self._version)
        # A build that predates this release has no section for it in its own
        # bundled changelog, so fall back to what the release itself says.
        if not text or text.lstrip().startswith("# Changelog"):
            text = self._release.get("body") or "No release notes available."
        notes.setMarkdown(text)
        root.addWidget(notes, stretch=1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setVisible(False)
        root.addWidget(self._bar)

        row = QHBoxLayout()
        self._primary = QPushButton()
        self._primary.setObjectName("primaryButton")
        self._primary.clicked.connect(self._on_primary)
        row.addWidget(self._primary)

        page_btn = QPushButton("Open Releases Page")
        page_btn.setToolTip("View this release on GitHub in your browser")
        page_btn.clicked.connect(self._open_page)
        row.addWidget(page_btn)
        row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        root.addLayout(row)

        self.progress.connect(self._on_progress, Qt.QueuedConnection)
        self.downloaded.connect(self._on_downloaded, Qt.QueuedConnection)
        self.installed.connect(self._on_installed, Qt.QueuedConnection)
        self.failed.connect(self._on_failed, Qt.QueuedConnection)

        self._configure_primary()

    # ---- what the button offers --------------------------------------------

    def _configure_primary(self) -> None:
        if self._asset is None:
            self._primary.setEnabled(False)
            self._primary.setText("No build for this system")
            self._primary.setToolTip(
                "This release has no attached build matching this platform."
            )
            self._status.setText(
                "The release has no downloadable build for this system — use the "
                "releases page."
            )
            return

        size = int(self._asset.get("size") or 0)
        if self._can_install:
            self._primary.setText("Update and Restart")
            self._primary.setToolTip(
                f"Download {_human(size)}, install it alongside the current "
                "version, and restart into it"
            )
            self._status.setText(
                "The current version is kept, so this can be undone by picking "
                "it again — nothing is overwritten."
            )
        else:
            self._primary.setText(f"Download ({_human(size)})" if size else "Download")
            self._primary.setToolTip("Download the build to your Downloads folder")
            self._status.setText(self._why_not)

    # ---- the pipeline -------------------------------------------------------

    def _on_primary(self) -> None:
        if self._thread is not None:
            self._cancel.set()
            self._primary.setEnabled(False)
            self._status.setText("Cancelling…")
            return

        self._cancel.clear()
        self._bar.setVisible(True)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._primary.setText("Cancel")

        install = self._can_install
        target = (
            os.path.join(update_check.downloads_dir())
            if not install
            else os.path.join(install_layout.detect().versions_dir, ".downloads")
        )

        def run() -> None:
            try:
                self.progress.emit(0, 0, "Downloading…")
                path = update_check.download_asset(
                    self._asset,
                    target,
                    on_progress=lambda got, total: self.progress.emit(
                        got, total, "Downloading…"
                    ),
                    cancelled=self._cancel.is_set,
                )
                if path is None:
                    self.failed.emit("")
                    return

                if not self._verify(path):
                    return

                if not install:
                    self.downloaded.emit(path)
                    return

                self.progress.emit(0, 0, "Installing…")
                layout = install_layout.detect()
                update_install.install_release(
                    path, self._version, layout, install_layout.app_binary_name()
                )
                install_layout.write_current(layout, self._version)
                # Not pruned here: the version being replaced has to survive
                # until the new one has proved it starts. clear_launching()
                # does it on the next successful launch.
                try:
                    os.remove(path)
                except OSError:
                    pass
                self.installed.emit(self._version)
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

        self._thread = threading.Thread(target=run, name="update-apply", daemon=True)
        self._thread.start()

    def _verify(self, path: str) -> bool:
        """Check the download against a published digest, when there is one."""
        self.progress.emit(0, 0, "Verifying…")
        sums = ""
        for asset in self._release.get("assets") or []:
            if str(asset.get("name", "")).upper().startswith("SHA256SUMS"):
                try:
                    sums = update_check.fetch_text(asset.get("browser_download_url"))
                except Exception:
                    sums = ""
                break

        digest = update_install.expected_digest(self._asset, sums)
        if not digest:
            # Nothing published to compare against. TLS to github.com is still
            # doing the real work here; say so rather than implying a check
            # happened.
            self.progress.emit(0, 0, "No checksum published — skipping verification")
            return True

        if update_install.verify(path, digest):
            return True

        try:
            os.remove(path)
        except OSError:
            pass
        self.failed.emit(
            "The download did not match its published checksum and was deleted. "
            "Try again, or download it from the releases page."
        )
        return False

    # ---- results ------------------------------------------------------------

    def _on_progress(self, received: int, total: int, label: str) -> None:
        if total > 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(int(received * 100 / total))
            self._status.setText(f"{label} {_human(received)} of {_human(total)}")
        else:
            # No Content-Length, or a step with no measurable size: show motion
            # rather than a bar stuck at zero.
            self._bar.setRange(0, 0)
            self._status.setText(label)

    def _on_downloaded(self, path: str) -> None:
        self._thread = None
        self._bar.setVisible(False)
        self._primary.setText("Show in Folder")
        self._primary.setEnabled(True)
        try:
            self._primary.clicked.disconnect()
        except TypeError:
            pass
        self._primary.clicked.connect(lambda: reveal(path))
        self._status.setText(
            f"Saved to {path}\nUnpack it and run it from there — nothing was "
            "installed or replaced, and your settings and data are untouched."
        )

    def _on_installed(self, version: str) -> None:
        self._thread = None
        self._bar.setVisible(False)
        self._primary.setEnabled(True)
        self._status.setText(f"{version} is installed.")

        answer = QMessageBox.question(
            self,
            "Restart Now",
            f"Version {version} is installed and will run when the app restarts.\n\n"
            "Restart now? Your combat is saved first, and the current version is "
            "kept in case you want to go back.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            self._primary.setText("Restart Now")
            try:
                self._primary.clicked.disconnect()
            except TypeError:
                pass
            self._primary.clicked.connect(self._restart)
            return
        self._restart()

    def _restart(self) -> None:
        layout = install_layout.detect()
        if layout is None:
            return
        tracker = self._tracker
        # Save before spawning: the launcher waits for this process to exit, so
        # the new one cannot race the old one's final write.
        if tracker is not None:
            for step in ("save_state", "save_layout"):
                try:
                    getattr(tracker, step)()
                except Exception:
                    pass
        try:
            update_install.relaunch(layout)
        except Exception as exc:
            QMessageBox.warning(
                self, "Restart Failed",
                f"The update is installed, but the app could not be restarted:\n{exc}\n\n"
                "Closing and reopening it will run the new version.",
            )
            return
        self.accept()
        QApplication.instance().quit()

    def _on_failed(self, message: str) -> None:
        self._thread = None
        self._bar.setVisible(False)
        self._primary.setEnabled(True)
        self._configure_primary()
        if message:
            self._status.setText(f"Update failed: {message}")
        else:
            self._status.setText("Cancelled.")

    def _open_page(self) -> None:
        url = self._release.get("html_url") or update_check.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def reject(self) -> None:
        self._cancel.set()
        super().reject()
