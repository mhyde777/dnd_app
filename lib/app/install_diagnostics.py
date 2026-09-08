# lib/app/install_diagnostics.py
"""
What kind of installation is this, and can it update itself?

`can_self_update()` answers yes/no with one sentence, which is right for the
update dialog but not enough to act on when the answer is no — the sentence
names a cause without showing the state it was derived from. This assembles
that state: where the app is, what the layout looks like, which checks pass.

Written to the log at startup as well as shown on demand, so a report that
begins "updating doesn't work on my Windows machine" arrives with the answer
already attached rather than needing a round trip to find out.

Qt-free, so it can be tested headlessly and logged before any window exists.
"""
from __future__ import annotations

import os
import platform
import sys
from typing import List, Tuple


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def collect() -> List[Tuple[str, str]]:
    """(label, value) pairs describing this installation. Never raises."""
    from app import appimage, install_layout
    from app.version import __version__

    rows: List[Tuple[str, str]] = [
        ("Version", __version__),
        ("Platform", f"{platform.system()} {platform.release()} ({platform.machine()})"),
        ("Packaged build", _yes_no(install_layout.running_frozen())),
    ]

    try:
        running_from = install_layout.running_dir()
    except Exception as exc:
        running_from = f"(could not determine: {exc})"
    rows.append(("Running from", running_from))

    if appimage.running_as_appimage():
        rows.append(("AppImage", appimage.appimage_path() or "(unknown path)"))

    layout = None
    try:
        layout = install_layout.detect()
    except Exception:
        pass

    if layout is None:
        rows.append(("Install layout", "not a versioned install"))
    else:
        rows.append(("Install root", layout.root))
        rows.append(("Running version", layout.version))
        rows.append(("Selected version (current)",
                     install_layout.read_current(layout) or "(unreadable)"))
        rows.append(("Installed versions",
                     ", ".join(layout.installed_versions()) or "(none found)"))
        # The three things can_self_update() checks beyond the layout existing.
        # Shown individually because "it says no" is not actionable, and which
        # one failed is the whole answer.
        rows.append((f"Launcher present ({install_layout.launcher_binary_name()})",
                     _yes_no(layout.has_launcher())))
        rows.append(("Install root writable",
                     _yes_no(os.access(layout.root, os.W_OK))))

    try:
        can, why = install_layout.can_self_update()
    except Exception as exc:
        can, why = False, f"(check failed: {exc})"
    rows.append(("Can install updates", _yes_no(can)))
    if not can and why:
        rows.append(("Reason", why))

    return rows


def as_text() -> str:
    """The same thing as a block of text, for the log and for copy-to-clipboard."""
    rows = collect()
    width = max((len(label) for label, _ in rows), default=0)
    return "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)


def log_summary(log) -> None:
    """Write a one-line summary at startup, and the detail when it matters.

    A line per field on every launch would drown the log. The summary is always
    useful; the full block is written only when updating is unavailable, which
    is exactly when someone will be reading the log to find out why.
    """
    try:
        from app import install_layout

        can, why = install_layout.can_self_update()
        if can:
            log("[Install] Updates can be installed in place.")
            return
        log(f"[Install] Updates cannot be installed in place: {why}")
        for line in as_text().splitlines():
            log(f"[Install] {line}")
    except Exception as exc:
        log(f"[WARN] Could not determine the install state: {exc}")
