from dotenv import load_dotenv
load_dotenv()
import os, sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from ui.ui import InitiativeTracker
from ui.theme import get_stylesheet
import qdarktheme

def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    qdarktheme.enable_hi_dpi()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("images/d20_icon.png")))
    qdarktheme.setup_theme("dark")
    app.setStyleSheet(app.styleSheet() + get_stylesheet())
    mainWin = InitiativeTracker()
    mainWin.showMaximized()
    sys.exit(app.exec_())
