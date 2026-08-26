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

    qdarktheme.enable_hi_dpi()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("images/d20_icon.png")))
    qdarktheme.setup_theme("dark")
    app.setStyleSheet(app.styleSheet() + get_stylesheet())

    # Show setup wizard on first run (no settings.json yet)
    import app.settings as settings
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

    sys.exit(app.exec_())
