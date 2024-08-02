import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from ui.ui import InitiativeTracker
import qdarktheme

if __name__ == "__main__":
    qdarktheme.enable_hi_dpi()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('images/d20_icon.png'))
    qdarktheme.setup_theme("auto")
    mainWin = InitiativeTracker()
    mainWin.showMaximized()
    sys.exit(app.exec_())
