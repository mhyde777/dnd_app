# lib/ui/appimage_install_dialog.py
"""
The AppImage's offer to install itself, and the File menu entry that repeats it.

The AppImage exists so that getting the app is one download and a double-click.
The cost is that it cannot update itself -- it is a read-only image with no
versions/ directory to install a new build beside. This dialog buys that back:
one click copies the payload into ~/.local/opt in the ordinary layout, adds a
desktop entry, and from then on Help -> Check for Updates works normally.

Offered, never automatic. Writing into someone's home directory the first time
they run a downloaded file is not something to do unasked, and running it from
Downloads without installing is a legitimate choice -- so "Not now" is a real
answer and is remembered.

The copying itself lives in app/appimage.py, which is Qt-free and tested
headlessly; this file is only the conversation with the user.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from app import appimage
from app.version import __version__

# Set once the user has been asked, whatever they answered. Being asked twice
# about the same thing reads as the app not listening.
PROMPTED_KEY = "appimage_install_prompted"


def _install_target() -> str:
    return appimage.install_root()


def available() -> bool:
    """True when installing is something this process could actually do."""
    return appimage.running_as_appimage() and appimage.payload_dir() is not None


def maybe_offer_install(parent) -> None:
    """Ask once, on a run where installing would help. Never raises."""
    try:
        if not available():
            return
        from app import settings

        if settings.get(PROMPTED_KEY):
            return
        if appimage.already_installed(__version__):
            settings.set(PROMPTED_KEY, True)
            return

        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Install Combat Tracker")
        box.setText("Add Combat Tracker to your applications?")
        box.setInformativeText(
            "You are running Combat Tracker straight from the file you "
            "downloaded. Installing it will:\n\n"
            "    •  add it to your applications menu\n"
            "    •  let it update itself when new versions come out\n\n"
            "Nothing is downloaded and your encounters and settings are not "
            "affected. You can also carry on using the downloaded file — it "
            "works exactly as it does now."
        )
        box.setDetailedText(
            f"Installs to: {_install_target()}\n"
            f"Menu entry:  ~/.local/share/applications/{appimage.DESKTOP_FILE_NAME}\n\n"
            "Nothing outside your home directory is touched, and no "
            "administrator password is needed."
        )
        install_btn = box.addButton("Install", QMessageBox.AcceptRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.setDefaultButton(install_btn)
        box.exec_()

        # Recorded whichever way they answered, and before the install runs: a
        # failed install should not mean being asked again on the next launch.
        settings.set(PROMPTED_KEY, True)

        if box.clickedButton() is install_btn:
            run_install(parent)
    except Exception:
        # A convenience prompt must never be the reason the app fails to start.
        pass


def run_install(parent) -> bool:
    """Install, report the outcome, and offer to restart into it."""
    from ui.notifications import report_error

    if not available():
        QMessageBox.information(
            parent,
            "Nothing to install",
            "This copy is not running as an AppImage, so there is nothing to "
            "install. It is already a normal installation.",
        )
        return False

    try:
        launcher = appimage.install(__version__)
    except Exception as exc:
        report_error(
            parent,
            "Could not install Combat Tracker",
            f"Installing to {_install_target()} failed. You can carry on using "
            "the downloaded file — it is unaffected.",
            exc,
        )
        return False

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("Installed")
    box.setText("Combat Tracker is installed.")
    box.setInformativeText(
        "You will find it in your applications menu. Updates now install "
        "themselves from Help → Check for Updates.\n\n"
        "You can delete the downloaded .AppImage file — it is no longer needed."
    )
    restart_btn = box.addButton("Restart now", QMessageBox.AcceptRole)
    box.addButton("Later", QMessageBox.RejectRole)
    box.setDefaultButton(restart_btn)
    box.exec_()

    if box.clickedButton() is restart_btn:
        _restart_into(launcher, parent)
    return True


def _restart_into(launcher: str, parent) -> None:
    """Start the installed copy and quit this one.

    Detached with start_new_session so the new process does not die with this
    one, and cwd is the install root rather than wherever the AppImage was run
    from -- usually Downloads, which is not somewhere to anchor a long-running
    process.
    """
    from ui.notifications import report_error

    try:
        window = parent.window() if parent is not None else None
        if window is not None and hasattr(window, "save_state"):
            # The two processes must not overlap writing settings; save before
            # handing over, the same as the updater's restart does.
            window.save_state()
    except Exception:
        pass

    try:
        subprocess.Popen(
            [launcher],
            cwd=os.path.dirname(launcher),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        report_error(
            parent,
            "Could not start the installed copy",
            f"Combat Tracker was installed to {launcher}, but starting it "
            "failed. Launch it from your applications menu instead.",
            exc,
        )
        return

    QApplication.quit()
    # quit() only asks the event loop to stop, and this process must be gone
    # before the new one gets far -- otherwise both hold the log open and both
    # write settings on close, and whichever quits second wins.
    sys.exit(0)
