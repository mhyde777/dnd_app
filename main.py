import sys
from PyQt5.QtWidgets import QApplication
from ui.ui import InitiativeTracker
import qdarktheme

if __name__ == "__main__":
    qdarktheme.enable_hi_dpi()
    app = QApplication(sys.argv)
    qdarktheme.setup_theme("auto")
    mainWin = InitiativeTracker()
    mainWin.showMaximized()
    sys.exit(app.exec_())
