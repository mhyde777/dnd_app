#!/usr/bin/env python3
"""
The stable entry point. Picks a version out of versions/ and runs it.

This is what the desktop entry and the Windows shortcut point at, and it is
deliberately tiny: it is the one piece an update cannot replace while it is
running, so it must almost never need to change. It has no dependencies beyond
the standard library on purpose -- it must start even when the app it launches
is broken.

    combat-tracker [--wait-pid PID] [-- ...args for the app]

--wait-pid is used by an update: the app writes the new `current`, starts this
with its own PID, and quits. Waiting means the old process is gone before the
new one opens the same config and log files.

Rollback: a `launching` file is written before starting a version and the app
removes it once its window is up. Finding one already there means that version
failed to start, so it is skipped and the previous one runs instead. Without
this, one bad build relaunches itself forever and the only fix is a file
manager.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

APP_BINARY = "combat_tracker"
LAUNCHER_LOG = "launcher.log"
VERSIONS_DIRNAME = "versions"
CURRENT_FILE = "current"
LAUNCHING_FILE = "launching"

_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[-+](.+))?$")
_WAIT_TIMEOUT = 30.0
_WAIT_STEP = 0.2


def root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def log(root: str, message: str) -> None:
    """Last-resort breadcrumbs. A launcher that fails silently is unfixable."""
    try:
        with open(os.path.join(root, LAUNCHER_LOG), "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except OSError:
        pass


def version_key(name: str) -> tuple:
    match = _VERSION_RE.match(name)
    if not match:
        return ((0,), 0, ())
    numbers = [int(p) for p in match.group(1).split(".")][:4]
    numbers += [0] * (4 - len(numbers))
    pre = match.group(2)
    return (tuple(numbers), 0 if pre else 1, tuple(pre.split(".")) if pre else ())


def installed_versions(root: str) -> list:
    versions_dir = os.path.join(root, VERSIONS_DIRNAME)
    try:
        names = os.listdir(versions_dir)
    except OSError:
        return []
    found = [
        name for name in names
        if _VERSION_RE.match(name) and os.path.isdir(os.path.join(versions_dir, name))
    ]
    return sorted(found, key=version_key, reverse=True)


def app_path(root: str, version: str) -> str:
    suffix = ".exe" if sys.platform == "win32" else ""
    return os.path.join(root, VERSIONS_DIRNAME, version, APP_BINARY + suffix)


def read_current(root: str) -> str:
    try:
        with open(os.path.join(root, CURRENT_FILE), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def wait_for_pid(pid: int) -> None:
    """Block until `pid` exits, or the timeout runs out.

    A timeout rather than waiting forever: if the old process is wedged, a
    second copy is a better outcome than a launcher that never returns.
    """
    deadline = time.time() + _WAIT_TIMEOUT
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(_WAIT_STEP)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def choose_version(root: str) -> str:
    """The version to run: `current`, unless it just failed to start."""
    versions = installed_versions(root)
    if not versions:
        return ""

    wanted = read_current(root)
    if wanted not in versions:
        wanted = versions[0]

    launching = os.path.join(root, LAUNCHING_FILE)
    failed = ""
    if os.path.exists(launching):
        try:
            with open(launching, "r", encoding="utf-8") as handle:
                failed = handle.read().strip()
        except OSError:
            failed = wanted
        try:
            os.remove(launching)
        except OSError:
            pass

    if failed and failed == wanted:
        fallback = [v for v in versions if v != failed]
        if fallback:
            log(root, f"{failed} did not start last time; falling back to {fallback[0]}")
            # Repoint `current` too, or every future launch pays the same
            # failed-start round trip.
            try:
                temp = os.path.join(root, CURRENT_FILE + ".tmp")
                with open(temp, "w", encoding="utf-8") as handle:
                    handle.write(fallback[0] + "\n")
                os.replace(temp, os.path.join(root, CURRENT_FILE))
            except OSError:
                pass
            return fallback[0]
        log(root, f"{failed} did not start last time, but it is the only version")
    return wanted


def main(argv: list) -> int:
    root = root_dir()

    wait_pid = 0
    passthrough = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--wait-pid" and index + 1 < len(argv):
            try:
                wait_pid = int(argv[index + 1])
            except ValueError:
                wait_pid = 0
            index += 2
            continue
        if arg == "--":
            passthrough = argv[index + 1:]
            break
        passthrough.append(arg)
        index += 1

    if wait_pid:
        wait_for_pid(wait_pid)

    version = choose_version(root)
    if not version:
        log(root, f"no versions found under {os.path.join(root, VERSIONS_DIRNAME)}")
        return 1

    target = app_path(root, version)
    if not os.path.isfile(target):
        log(root, f"{version} has no {os.path.basename(target)}")
        return 1

    try:
        with open(os.path.join(root, LAUNCHING_FILE), "w", encoding="utf-8") as handle:
            handle.write(version + "\n")
    except OSError:
        pass

    log(root, f"starting {version}")
    try:
        os.chmod(target, 0o755)
    except OSError:
        pass

    try:
        # Replace this process where we can, so no launcher lingers in the
        # process list or the taskbar for the whole session.
        if sys.platform == "win32":
            completed = subprocess.run([target] + passthrough)
            return completed.returncode
        os.execv(target, [target] + passthrough)
    except OSError as exc:
        log(root, f"could not start {target}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
