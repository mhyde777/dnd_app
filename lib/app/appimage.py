# lib/app/appimage.py
"""
Running as an AppImage, and turning that into a real installation.

An AppImage is one file the user downloads, marks executable and double-clicks
-- no terminal, no unpacking, no choosing a directory. That is the whole reason
to ship one, and it is why it is the primary Linux download.

What it cannot be is self-updating. The AppImage is a read-only squashfs image
mounted at run time, so there is no `versions/` directory to install a new
build beside and nothing writable to repoint. `install_layout.detect()`
correctly returns None inside one.

So the AppImage offers, once, to install itself: it copies the payload it is
already carrying into ~/.local/opt/combat-tracker in the ordinary versioned
layout, writes a desktop entry, and from then on the copy is an ordinary
install with working one-click updates. The user gets the zero-friction
download *and* the updates, at the cost of one dialog on first run.

Deliberately an offer and not automatic: an AppImage that silently wrote
itself into the user's home the first time it ran would be doing something the
user did not ask for, and "just run it once from the Downloads folder" is a
legitimate thing to want.

Qt-free on purpose -- the dialog lives in ui/appimage_install_dialog.py -- so
the copying can be tested headlessly.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Optional

# The AppImage runtime exports both: APPIMAGE is the path of the .AppImage file
# itself, APPDIR the read-only mount it was unpacked to. Neither exists outside
# one, which is what makes this a reliable check rather than a guess.
ENV_APPIMAGE = "APPIMAGE"
ENV_APPDIR = "APPDIR"

DEFAULT_INSTALL_DIR = "~/.local/opt/combat-tracker"
DESKTOP_FILE_NAME = "combat-tracker.desktop"
ICON_NAME = "combat_tracker.png"


def appimage_path() -> Optional[str]:
    """The .AppImage file we were started from, or None if we weren't."""
    if sys.platform != "linux":
        return None
    value = os.environ.get(ENV_APPIMAGE, "").strip()
    return value or None


def appdir() -> Optional[str]:
    """The mounted AppDir, or None."""
    value = os.environ.get(ENV_APPDIR, "").strip()
    return value or None


def running_as_appimage() -> bool:
    return appimage_path() is not None


def payload_dir() -> Optional[str]:
    """Where the build lives inside the mounted AppDir.

    build_appimage.sh puts the PyInstaller payload and the launcher together in
    usr/bin. Deliberately *not* under a directory called `versions`: that is the
    marker install_layout.detect() keys on, and a read-only mount that looked
    like an updatable install would offer a button that could only fail.
    """
    base = appdir()
    if not base:
        return None
    candidate = os.path.join(base, "usr", "bin")
    return candidate if os.path.isdir(candidate) else None


def install_root(override: Optional[str] = None) -> str:
    return os.path.abspath(os.path.expanduser(override or DEFAULT_INSTALL_DIR))


def already_installed(version: str, override: Optional[str] = None) -> bool:
    """True when this exact version is already installed at the target."""
    root = install_root(override)
    from app import install_layout

    return os.path.isdir(os.path.join(root, install_layout.VERSIONS_DIRNAME, version)) \
        and os.path.isfile(os.path.join(root, install_layout.launcher_binary_name()))


def _desktop_entry(launcher: str, icon: str) -> str:
    # Exec and Icon have to be absolute: a desktop entry is read by the desktop
    # environment, which has neither our working directory nor our PATH.
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Combat Tracker\n"
        "Comment=Initiative, HP and conditions for D&D 5e\n"
        f"Exec={launcher}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Game;\n"
        "StartupWMClass=combat_tracker\n"
    )


def write_desktop_entry(launcher: str, icon: str) -> Optional[str]:
    """Add the app to the applications menu. Returns the path, or None.

    Never fatal: an install whose desktop entry failed is still an install the
    user can run, so a failure here must not lose them the rest of it.
    """
    apps_dir = os.path.expanduser("~/.local/share/applications")
    try:
        os.makedirs(apps_dir, exist_ok=True)
        path = os.path.join(apps_dir, DESKTOP_FILE_NAME)
        # Written and renamed rather than truncated in place: a desktop file
        # caught half-written is a menu entry that silently does nothing.
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(_desktop_entry(launcher, icon))
        os.replace(temp, path)
        os.chmod(path, 0o644)
    except OSError:
        return None

    # Best-effort: most desktops pick the file up without being told.
    try:
        import subprocess

        subprocess.run(
            ["update-desktop-database", apps_dir],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass
    return path


def install(version: str, override: Optional[str] = None,
            source: Optional[str] = None) -> str:
    """Copy the running AppImage's payload into a real install. Returns the
    launcher path.

    Lays down exactly the layout install_layout describes, so the result is
    indistinguishable from a tarball install and Help -> Check for Updates
    works on it from then on.

    Raises RuntimeError when there is nothing to copy, and lets OSError out --
    a half-finished install must not be reported as a success.
    """
    from app import install_layout

    src = source or payload_dir()
    if not src or not os.path.isdir(src):
        raise RuntimeError("no AppImage payload to install from")

    launcher_name = install_layout.launcher_binary_name()
    app_name = install_layout.app_binary_name()
    src_launcher = os.path.join(src, launcher_name)
    if not os.path.isfile(src_launcher):
        raise RuntimeError(f"{launcher_name} is missing from the AppImage payload")

    root = install_root(override)
    versions = os.path.join(root, install_layout.VERSIONS_DIRNAME)
    target = os.path.join(versions, version)
    staging = target + ".incoming"

    os.makedirs(versions, exist_ok=True)
    # Staged under a name the launcher will not run, then renamed into place --
    # the same reason update_install.py does it. A rename within one directory
    # is as close to atomic as this gets, so the launcher can never catch a
    # half-copied version: a half-copied one is not yet called by its version
    # name.
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    if os.path.isdir(target):
        shutil.rmtree(target)

    # The launcher is copied to the root, not into the version -- it is the
    # stable entry point that survives every update.
    shutil.copytree(src, staging, symlinks=True,
                    ignore=shutil.ignore_patterns(launcher_name))
    inner = os.path.join(staging, app_name)
    if not os.path.isfile(inner):
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"{app_name} is missing from the AppImage payload")
    os.chmod(inner, 0o755)
    os.replace(staging, target)

    launcher = os.path.join(root, launcher_name)
    shutil.copy2(src_launcher, launcher)
    os.chmod(launcher, 0o755)

    icon = os.path.join(root, ICON_NAME)
    for candidate in (os.path.join(src, ICON_NAME),
                      os.path.join(appdir() or "", ICON_NAME)):
        if candidate and os.path.isfile(candidate):
            shutil.copy2(candidate, icon)
            break

    install_layout.write_current(install_layout.Layout(root=root, version=version), version)
    write_desktop_entry(launcher, icon if os.path.isfile(icon) else "")
    return launcher
