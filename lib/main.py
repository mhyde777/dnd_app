import sys
from PyQt5.QtWidgets import QApplication
from ui.ui import InitiativeTracker

if __name__ == "__main__":
    app = QApplication(sys.argv)
    mainWin = InitiativeTracker()
    mainWin.show()
    sys.exit(app.exec_())
