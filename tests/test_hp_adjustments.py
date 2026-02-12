import sys
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

from app.creature import Monster, I_Creature


class HpAdjustmentTests(unittest.TestCase):
    def test_damage_consumes_temp_hp_before_curr_hp(self):
        creature = Monster(name="Ogre", max_hp=30, curr_hp=30, temp_hp=8)

        hp_damage = creature.apply_damage(12)

        self.assertEqual(hp_damage, 4)
        self.assertEqual(creature.temp_hp, 0)
        self.assertEqual(creature.curr_hp, 26)

    def test_healing_caps_at_effective_max_hp(self):
        creature = Monster(name="Cleric", max_hp=20, max_hp_bonus=5, curr_hp=18)

        creature.apply_healing(20)

        self.assertEqual(creature.curr_hp, 25)

    def test_serialization_round_trip_preserves_temp_and_bonus_hp(self):
        creature = Monster(name="Tank", max_hp=40, max_hp_bonus=10, curr_hp=39, temp_hp=6)
        payload = creature.to_dict()

        restored = I_Creature.from_dict(payload)

        self.assertEqual(restored.max_hp_bonus, 10)
        self.assertEqual(restored.temp_hp, 6)
        self.assertEqual(restored.effective_max_hp, 50)


if __name__ == "__main__":
    unittest.main()
