"""
Progress UI for installing the bundled SRD library into a storage backend.

The work runs on a worker thread. That is not decoration: installing into a
remote API is ~670 HTTP PUTs, and doing it on the Qt thread would freeze the
window for as long as the server takes. Cancel therefore has to actually
work -- it sets an event the worker checks between entries, so a cancelled
install stops promptly and leaves a consistent partial state that the next
run resumes from.
"""
from __future__ import annotations

import threading
from typing import Iterable, Optional

from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox, QProgressDialog

from app import srd_content
from app.content_installer import InstallResult, install_srd


class _InstallWorker(QObject):
    progress = pyqtSignal(str, int, int, str)   # category, index, total, key
    finished = pyqtSignal(object)               # InstallResult

    def __init__(self, storage, categories, cancel: threading.Event) -> None:
        super().__init__()
        self._storage = storage
        self._categories = list(categories)
        self._cancel = cancel

    def run(self) -> None:
        try:
            result = install_srd(
                self._storage,
                categories=self._categories,
                progress=lambda c, i, t, k: self.progress.emit(c, i, t, k),
                cancel=self._cancel,
            )
        except Exception as exc:  # a backend blowing up shouldn't hang the dialog
            result = InstallResult()
            result.failed.append(str(exc))
        self.finished.emit(result)


_CATEGORY_LABELS = {"statblocks": "monsters", "spells": "spells"}


def run_install(
    parent,
    storage,
    categories: Iterable[str],
    destination: str,
) -> Optional[InstallResult]:
    """Install `categories` into `storage`, showing progress. Blocks until done.

    Returns the result, or None if there was nothing to do.
    """
    categories = [c for c in categories if c in srd_content.CATEGORIES]
    if not categories or storage is None or not srd_content.is_available():
        return None

    counts = srd_content.counts()
    total = sum(counts.get(c, 0) for c in categories) or 1

    dialog = QProgressDialog(
        f"Installing SRD content into {destination}…", "Cancel", 0, total, parent
    )
    dialog.setWindowTitle("Installing Content")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumWidth(420)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setValue(0)

    cancel = threading.Event()
    dialog.canceled.connect(cancel.set)

    thread = QThread(parent)
    worker = _InstallWorker(storage, categories, cancel)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    # Entries are counted per category; the bar is over the whole job, so each
    # category's index is offset by the ones already done.
    offsets = {}
    running = 0
    for category in categories:
        offsets[category] = running
        running += counts.get(category, 0)

    def on_progress(category: str, index: int, _total: int, key: str) -> None:
        dialog.setValue(min(offsets.get(category, 0) + index, total))
        label = _CATEGORY_LABELS.get(category, category)
        dialog.setLabelText(
            f"Installing SRD {label} into {destination}…\n{key.removesuffix('.json')}"
        )

    outcome: dict = {}

    def on_finished(result: InstallResult) -> None:
        outcome["result"] = result
        thread.quit()

    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    thread.start()

    while thread.isRunning():
        QApplication.processEvents()
        thread.wait(30)

    worker.deleteLater()
    thread.deleteLater()
    dialog.close()

    result: InstallResult = outcome.get("result") or InstallResult()

    if result.failed:
        QMessageBox.warning(
            parent,
            "Content Install",
            f"{result.summary()}.\n\nFirst failures:\n"
            + "\n".join(result.failed[:8]),
        )
    elif result.cancelled:
        QMessageBox.information(
            parent,
            "Content Install",
            f"Install cancelled — {result.summary()}.\n\n"
            "Nothing was lost; running it again picks up where this left off.",
        )

    return result
