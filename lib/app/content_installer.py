"""
Install the bundled SRD library into whichever storage backend is configured.

Every provider exposes the same save/list methods (see `app.storage.base`), so
one code path serves all of them. That matters for the network-backed ones:
installing into WebDAV, S3 or an HTTP server is ~670 requests over a possibly
slow link, so the work is interruptible and re-running it is cheap.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from app import srd_content

# (category, index, total, key) -> None
ProgressCallback = Callable[[str, int, int, str], None]


@dataclass
class InstallResult:
    installed: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    cancelled: bool = False

    def summary(self) -> str:
        parts = [f"{self.installed} installed"]
        if self.skipped:
            parts.append(f"{self.skipped} already present")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if self.cancelled:
            parts.append("cancelled")
        return ", ".join(parts)


def install_srd(
    storage,
    categories: Iterable[str] = srd_content.CATEGORIES,
    progress: Optional[ProgressCallback] = None,
    skip_existing: bool = True,
    cancel: Optional[threading.Event] = None,
) -> InstallResult:
    """Copy bundled SRD entries into `storage`.

    `skip_existing` is what makes a cancelled run resumable, and it also means
    a user's own edits to an entry are never overwritten by a re-run.
    """
    result = InstallResult()

    for category in categories:
        if category not in srd_content.CATEGORIES:
            continue
        list_name, save_name = srd_content.STORAGE_METHODS[category]
        save = getattr(storage, save_name, None)
        if save is None:
            continue

        existing: set[str] = set()
        if skip_existing:
            lister = getattr(storage, list_name, None)
            if lister is not None:
                try:
                    existing = set(lister() or ())
                except Exception:
                    # A backend that can't be listed is not a reason to refuse
                    # to install; it just means nothing can be skipped.
                    existing = set()

        total = srd_content.counts().get(category, 0)
        for index, (key, data) in enumerate(srd_content.iter_entries(category), 1):
            if progress is not None:
                progress(category, index, total, key)

            # Checked after reporting and before writing, so Cancel takes
            # effect on the entry the dialog is currently showing rather than
            # letting one more through.
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                return result

            if key in existing:
                result.skipped += 1
                continue

            try:
                ok = save(key, data)
            except Exception:
                ok = False
            if ok is False:
                result.failed.append(f"{category}/{key}")
            else:
                result.installed += 1

    return result


def install_marker(result: InstallResult, destination: str) -> dict:
    """The settings record of what was installed where.

    Kept so a later release can offer to add what's new instead of silently
    rewriting entries the user may have edited since.
    """
    return {
        "version": srd_content.version(),
        "destination": destination,
        "installed": result.installed,
        "skipped": result.skipped,
    }
