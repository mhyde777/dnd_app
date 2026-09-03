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

    from app.creature import I_Creature, Monster
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

    def test_tied_initiative_breaks_on_dexterity(self):
        manager = CreatureManager()
        manager.add_creature(
            [
                Monster(name="Adept", init=17, dex=10),
                Monster(name="Zealot", init=17, dex=18),
                Monster(name="Brute", init=17, dex=14),
            ]
        )

        self.assertEqual(manager.ordered_names(), ["Zealot", "Brute", "Adept"])

    def test_dexterity_never_outranks_initiative(self):
        manager = CreatureManager()
        manager.add_creature(
            [
                Monster(name="Sluggard", init=20, dex=6),
                Monster(name="Duelist", init=19, dex=20),
            ]
        )

        self.assertEqual(manager.ordered_names(), ["Sluggard", "Duelist"])

    def test_unknown_dexterity_sorts_after_known_then_by_name(self):
        """A PC nobody typed a DEX for must not be ranked as if it had one."""
        manager = CreatureManager()
        manager.add_creature(
            [
                Monster(name="Aaron", init=12),
                Monster(name="Zara", init=12, dex=8),
                Monster(name="Bella", init=12),
            ]
        )

        self.assertEqual(manager.ordered_names(), ["Zara", "Aaron", "Bella"])

    def test_equal_dexterity_falls_back_to_natural_name_order(self):
        manager = CreatureManager()
        manager.add_creature(
            [
                Monster(name="Goblin 10", init=12, dex=14),
                Monster(name="Goblin 2", init=12, dex=14),
            ]
        )

        self.assertEqual(manager.ordered_names(), ["Goblin 2", "Goblin 10"])

    def test_dexterity_survives_a_save_load_round_trip(self):
        original = Monster(name="Scout", init=15, dex=16)
        restored = I_Creature.from_dict(original.to_dict())
        self.assertEqual(restored.dex, 16)

        legacy = I_Creature.from_dict(
            {k: v for k, v in original.to_dict().items() if k != "_dex"}
        )
        self.assertEqual(legacy.dex, -1)


if __name__ == "__main__":
    unittest.main()
