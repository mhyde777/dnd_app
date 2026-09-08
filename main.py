import os, sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
import qdarktheme

def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    from ui.theme import get_stylesheet
    from app.app_log import configure as configure_logging
    from ui.notifications import install_excepthook

    configure_logging()
    # Without this an exception inside a Qt slot vanishes into a stdout nobody
    # sees in a packaged build, and the app just looks unresponsive.
    install_excepthook()

    # Record up front whether this copy can install its own updates, and the
    # state behind that answer when it cannot. "Updating doesn't work" is
    # otherwise a report with no evidence in it, and the cause is usually
    # something invisible from inside the app -- an install extracted into a
    # directory the user cannot write to, or a pre-launcher layout. Logged
    # here rather than in clear_launching(), which returns early for exactly
    # the layouts worth diagnosing.
    from app.app_log import get_logger
    from app.install_diagnostics import log_summary
    log_summary(get_logger().info)

    qdarktheme.enable_hi_dpi()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("images/d20_icon.png")))
    qdarktheme.setup_theme("dark")
    app.setStyleSheet(app.styleSheet() + get_stylesheet())

    # Rewrite pre-provider storage settings into the current shape before
    # anything reads them. A no-op on a fresh profile and on an install that
    # has already been through it; it never removes the old keys, so
    # downgrading to a previous build still finds what it expects.
    import app.settings as settings
    from app.config import migrate_legacy_storage
    migrate_legacy_storage()

    # Show setup wizard on first run (no settings.json yet)
    if not settings.settings_exist():
        from ui.setup_wizard import SetupWizard
        wizard = SetupWizard()
        if wizard.exec_() != wizard.Accepted:
            sys.exit(0)

    from ui.ui import InitiativeTracker
    mainWin = InitiativeTracker()
    # Restored geometry is kept as the un-maximized size, but the app always
    # opens maximized.
    mainWin.showMaximized()

    # Tell the launcher this version started. It writes a marker before running
    # us and treats one it finds still there as "that build is broken", falling
    # back to the previous version -- so clearing it has to happen only once a
    # window is actually up, not at import time.
    from PyQt5.QtCore import QTimer
    from app.install_layout import clear_launching
    QTimer.singleShot(0, clear_launching)

    # An AppImage cannot update itself, so offer once to turn it into a real
    # install that can. After the window is up, not before: the first thing a
    # new user should see is the app, not a question about where to put it.
    from ui.appimage_install_dialog import maybe_offer_install
    QTimer.singleShot(0, lambda: maybe_offer_install(mainWin))

    sys.exit(app.exec_())
