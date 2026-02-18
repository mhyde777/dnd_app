"""
Quick preview script for statblock components. Run with:

    pipenv run python preview_statblock.py [mode] [fixture_name]

Modes:
    widget  (default) — show StatblockWidget with a parsed fixture
    dialog            — open the StatblockImportDialog (paste & preview)

fixture_name defaults to 'goblin_2014'. Other options:
    goblin_2024  mage_2014  mage_2024  adult_red_dragon_2014
"""
import sys
import os

# Add lib to path so imports work without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))

from PyQt5.QtWidgets import QApplication, QMainWindow, QSizePolicy, QDialog
from app.statblock_parser import parse_statblock
from ui.statblock_widget import StatblockWidget
from ui.statblock_import_dialog import StatblockImportDialog

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "tests", "fixtures")


def preview_widget(fixture: str) -> QMainWindow:
    fixture_path = os.path.join(FIXTURES_DIR, f"{fixture}.txt")
    if not os.path.exists(fixture_path):
        print(f"Fixture not found: {fixture_path}")
        print("Available:", [f[:-4] for f in os.listdir(FIXTURES_DIR) if f.endswith(".txt")])
        sys.exit(1)

    with open(fixture_path) as f:
        data = parse_statblock(f.read())

    window = QMainWindow()
    window.setWindowTitle(f"Statblock Preview — {data.get('name', fixture)}")
    window.resize(420, 700)

    widget = StatblockWidget()
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    widget.load_statblock(data)
    window.setCentralWidget(widget)
    window.show()
    return window


def preview_dialog() -> None:
    # No storage_api — save button will show a "not configured" message
    dlg = StatblockImportDialog(storage_api=None)
    dlg.setWindowTitle("Import Statblock — Preview (save disabled)")
    dlg.exec_()


def main():
    args = sys.argv[1:]
    mode = "widget"
    fixture = "goblin_2014"

    if args and args[0] == "dialog":
        mode = "dialog"
        args = args[1:]
    if args:
        fixture = args[0]

    app = QApplication(sys.argv)

    if mode == "dialog":
        preview_dialog()
    else:
        window = preview_widget(fixture)  # keep reference alive for event loop
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()
