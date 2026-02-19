import importlib.util
import os
import sys
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PYQT_AVAILABLE = importlib.util.find_spec("PyQt5") is not None

if PYQT_AVAILABLE:
    from PyQt5.QtCore import QCoreApplication

    #Ensure imports resolve without installation
    REPO_ROOT = Path(__file__).resolve().parents[1]
    LIB_DIR = REPO_ROOT / "lib"
    sys.path.insert(0, str(LIB_DIR))

    from app.creature import Monster
    from app.manager import CreatureManager
    from ui.creature_table_model import CreatureTableModel 

@unittest.skipUnless(PYQT_AVAILABLE, "PyQt5 is required for UI ordering checks.")
class InitiativeOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Some Qt classes expect an application instance
        cls._qt_app = QCoreApplication.instance() or QCoreApplication([])

    def test_table_and_navigation_share_tie_breaking_order(self):
        manager = CreatureManager()
        manager.add_creature(
            [
                Monster(name="Goblin 10", init=12, max_hp=7, curr_hp=7, armor_class=15),
                Monster(name="Goblin 2", init=12, max_hp=7, curr_hp=7, armor_class=15),
            ]
        )

        model = CreatureTableModel(manager)
        model.refresh()

        navigation_order = manager.ordered_names()
        self.assertEqual(navigation_order, ["Goblin 2", "Goblin 10"])
        self.assertEqual(model.creature_names, navigation_order)


if __name__ == "__main__":
    unittest.main()
