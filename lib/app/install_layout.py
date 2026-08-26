# lib/app/install_layout.py
"""
Where the app is installed, and whether it can update itself in place.

The layout that makes one-click updating possible:

    <root>/
        combat-tracker[.exe]     the launcher -- stable, rarely changes
        versions/
            0.2.0/               a whole PyInstaller one-folder build
                combat_tracker[.exe]
                _internal/
            0.3.0/
        current                  text file naming the version to run
        launching                written before a start, cleared once the UI is up

A new version is unpacked into `versions/<new>/` and `current` is repointed at
it. The running build is never written to, which is the entire trick: on
Windows a running .exe and its loaded DLLs are held open and cannot be
replaced, and on every platform a PyInstaller folder loads files lazily, so
overwriting one underneath a live process is a crash waiting to happen. Adding
a directory beside it sidesteps all of that.

`launching` is the rollback. The launcher writes it, the app clears it once it
has a window up; finding a stale one means that version failed to start, so the
launcher falls back to the previous one instead of relaunching a broken build
forever.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import List, Optional

APP_BINARY = "combat_tracker"
LAUNCHER_BINARY = "combat-tracker"
VERSIONS_DIRNAME = "versions"
CURRENT_FILE = "current"
LAUNCHING_FILE = "launching"

_VERSION_DIR_RE = re.compile(r"^\d+(?:\.\d+)*(?:[-+].+)?$")


def _exe_suffix() -> str:
    return ".exe" if sys.platform == "win32" else ""


def app_binary_name() -> str:
    return APP_BINARY + _exe_suffix()


def launcher_binary_name() -> str:
    return LAUNCHER_BINARY + _exe_suffix()


def running_frozen() -> bool:
    """True in a PyInstaller build, false under `python main.py`."""
    return bool(getattr(sys, "frozen", False))


def running_dir() -> str:
    """The directory holding the running executable (or main.py in source)."""
    if running_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Layout:
    """A versioned installation the app can update itself within."""

    root: str
    version: str

    @property
    def versions_dir(self) -> str:
        return os.path.join(self.root, VERSIONS_DIRNAME)

    @property
    def current_file(self) -> str:
        return os.path.join(self.root, CURRENT_FILE)

    @property
    def launching_file(self) -> str:
        return os.path.join(self.root, LAUNCHING_FILE)

    @property
    def launcher(self) -> str:
        return os.path.join(self.root, launcher_binary_name())

    def version_dir(self, version: str) -> str:
        return os.path.join(self.versions_dir, version)

    def installed_versions(self) -> List[str]:
        try:
            names = os.listdir(self.versions_dir)
        except OSError:
            return []
        return sorted(
            name for name in names
            if _VERSION_DIR_RE.match(name)
            and os.path.isdir(os.path.join(self.versions_dir, name))
        )

    def has_launcher(self) -> bool:
        return os.path.isfile(self.launcher)


def detect(start: Optional[str] = None) -> Optional[Layout]:
    """The versioned layout we are running inside, or None.

    None means a flat install from before this scheme, or a source checkout.
    Neither can be updated in place, and both should say so rather than
    offering a button that would do something surprising.
    """
    # The frozen check applies to "where am I running from?", not to a path the
    # caller named: an installed tree can be inspected from anywhere, and
    # tying the two together made this untestable outside a packaged build.
    if start is None and not running_frozen():
        return None

    here = os.path.abspath(start or running_dir())
    parent = os.path.dirname(here)
    if os.path.basename(parent) != VERSIONS_DIRNAME:
        return None

    root = os.path.dirname(parent)
    version = os.path.basename(here)
    if not _VERSION_DIR_RE.match(version):
        return None
    return Layout(root=root, version=version)


def read_current(layout: Layout) -> Optional[str]:
    try:
        with open(layout.current_file, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError:
        return None
    return value or None


def write_current(layout: Layout, version: str) -> None:
    """Point the launcher at `version`, atomically.

    Written to a temp file and renamed: a half-written `current` would leave
    the launcher unable to decide what to run.
    """
    temp = layout.current_file + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(version.strip() + "\n")
    os.replace(temp, layout.current_file)


HISTORY_KEY = "version_history"
KEEP_VERSIONS_KEY = "keep_versions"
# One. The superseded build is kept anyway until the new one has passed its
# self-check (see self_test.py) or served out its grace period -- so the spare
# exists exactly while it is useful, rather than permanently. Older ones are
# re-downloaded on demand instead of being stored forever.
DEFAULT_KEEP_VERSIONS = 1


def record_started(layout: Optional[Layout] = None) -> None:
    """Note in settings that this version ran, and when.

    The history outlives the build itself, which is the point: a version can be
    pruned off disk and still be offered as somewhere to go back to, because
    the release it came from is still downloadable.
    """
    from app import settings

    layout = layout or detect()
    version = layout.version if layout is not None else None
    if not version:
        return

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    history = [
        entry for entry in (settings.get(HISTORY_KEY) or [])
        if isinstance(entry, dict) and entry.get("version") != version
    ]
    previous = next(
        (e for e in (settings.get(HISTORY_KEY) or [])
         if isinstance(e, dict) and e.get("version") == version),
        {},
    )
    history.insert(0, {
        "version": version,
        "first_run": previous.get("first_run") or now,
        "last_run": now,
    })
    settings.set(HISTORY_KEY, history[:20])


def version_history() -> list:
    from app import settings

    return [
        entry for entry in (settings.get(HISTORY_KEY) or [])
        if isinstance(entry, dict) and entry.get("version")
    ]


GRACE_KEY = "version_grace_minutes"
RETIRE_KEY = "version_retire_at"
# Long enough to notice the new build is wrong in normal use -- a session, a
# fight, an evening -- without holding 140MB indefinitely.
DEFAULT_GRACE_MINUTES = 60


def grace_minutes() -> int:
    from app import settings

    try:
        value = int(settings.get(GRACE_KEY, DEFAULT_GRACE_MINUTES))
    except (TypeError, ValueError):
        return DEFAULT_GRACE_MINUTES
    return max(0, value)


def _retirements() -> dict:
    from app import settings

    stored = settings.get(RETIRE_KEY) or {}
    return dict(stored) if isinstance(stored, dict) else {}


def _save_retirements(mapping: dict) -> None:
    from app import settings

    settings.set(RETIRE_KEY, mapping)


def retire_at(version: str) -> Optional[datetime]:
    """When `version` becomes eligible for deletion, if it is on probation."""
    raw = _retirements().get(version)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def cancel_retirement(version: str) -> None:
    """Take a version off probation -- it has been chosen to run again."""
    mapping = _retirements()
    if mapping.pop(version, None) is not None:
        _save_retirements(mapping)


def prune_with_grace(layout: Optional[Layout] = None) -> tuple:
    """Delete versions whose probation has expired. Returns (removed, waiting).

    A build that falls outside the keep window is not deleted straight away.
    It is stamped with a retirement time and left alone until that passes, so
    a version that starts cleanly and only then turns out to be wrong is still
    there to go back to instantly.

    The stamp lives in settings rather than in memory: the probation has to
    survive the restart that an update performs, which is the only reason the
    old build is interesting in the first place.
    """
    from app.update_check import _parse
    from app.update_install import prune_versions

    layout = layout or detect()
    if layout is None:
        return [], {}

    keep = keep_versions()
    grace = grace_minutes()
    protected = {layout.version}
    selected = read_current(layout)
    if selected:
        protected.add(selected)

    versions = sorted(layout.installed_versions(), key=_parse, reverse=True)
    candidates = [v for v in versions[keep:] if v not in protected]

    now = datetime.now(timezone.utc)
    mapping = _retirements()
    changed = False
    waiting = {}
    expired = []

    for version in candidates:
        stamp = mapping.get(version)
        due = None
        if stamp:
            try:
                due = datetime.fromisoformat(stamp)
            except (TypeError, ValueError):
                due = None
        if due is None:
            due = now + timedelta(minutes=grace)
            mapping[version] = due.isoformat()
            changed = True
        if due <= now:
            expired.append(version)
        else:
            waiting[version] = due

    # Anything no longer a candidate (reinstalled, or now inside the keep
    # window) should not carry a stale retirement date.
    for version in list(mapping):
        if version not in candidates:
            mapping.pop(version)
            changed = True

    removed = []
    if expired:
        removed = prune_versions(
            layout,
            keep=keep,
            protect=[v for v in versions if v not in expired],
        )
        for version in removed:
            mapping.pop(version, None)
            changed = True

    if changed:
        _save_retirements(mapping)
    return removed, waiting


def keep_versions() -> int:
    from app import settings

    try:
        value = int(settings.get(KEEP_VERSIONS_KEY, DEFAULT_KEEP_VERSIONS))
    except (TypeError, ValueError):
        return DEFAULT_KEEP_VERSIONS
    return max(1, value)


def clear_launching(layout: Optional[Layout] = None) -> None:
    """Mark this version as having started, and tidy up behind it.

    Pruning happens here rather than at install time so the build being
    replaced survives until its replacement has actually proved it can start.
    Deleting it any earlier would throw away the thing the launcher falls back
    to at exactly the moment it might be needed.
    """
    layout = layout or detect()
    if layout is None:
        return
    try:
        os.remove(layout.launching_file)
    except OSError:
        pass

    record_started(layout)

    try:
        from app.app_log import get_logger

        removed, waiting = prune_with_grace(layout)
        if removed:
            get_logger().info("[Update] Removed old versions: %s", ", ".join(removed))
        for version, due in waiting.items():
            get_logger().info(
                "[Update] Keeping %s until %s in case this build misbehaves",
                version, due.isoformat(timespec="minutes"),
            )
    except Exception:
        # Housekeeping must never stop the app from finishing startup.
        pass


def can_self_update() -> tuple:
    """(possible, reason). `reason` is user-facing when possible is False."""
    if not running_frozen():
        return False, (
            "This is a source checkout, not an installed build — update it with git."
        )
    layout = detect()
    if layout is None:
        return False, (
            "This copy was installed before one-click updates existed. Download "
            "this release and unpack it once; updates after that are a single "
            "button."
        )
    if not layout.has_launcher():
        return False, (
            "The launcher is missing from this installation, so a new version "
            "could be installed but not started."
        )
    if not os.access(layout.root, os.W_OK):
        return False, (
            f"No permission to write to {layout.root}. Install somewhere you own, "
            "such as your home directory."
        )
    return True, ""
