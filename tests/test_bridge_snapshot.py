"""Applying a bridge snapshot: what it may and may not overwrite.

The regression: with Foundry closed, the bridge keeps serving its last
snapshot -- combat inactive, round 0 -- and the app rewrote the tracker's
round counter to 1 on every poll.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lib"))


def _snapshot(active, round_value, combatants=None):
    return {
        "combat": {
            "active": active,
            "activeCombatant": None,
            "id": "c1" if active else None,
            "round": round_value,
            "turn": 0,
        },
        "combatants": combatants or [],
        "source": "foundry",
        "world": "KGV",
    }


class _RoundOnly:
    """The round-handling slice of _apply_bridge_snapshot, isolated.

    Driving the real method needs a live Qt window and a populated manager;
    this keeps the rule itself under test without that scaffolding.
    """

    def __init__(self, round_counter):
        self.round_counter = round_counter

    def apply(self, snapshot):
        combat = snapshot.get("combat", {})
        if isinstance(combat, dict):
            round_value = combat.get("round")
            if (
                isinstance(round_value, int)
                and round_value >= 1
                and combat.get("active")
            ):
                self.round_counter = round_value
        return self.round_counter


class SnapshotRoundTests(unittest.TestCase):
    def test_inactive_combat_does_not_touch_the_round(self):
        # Exactly what the bridge serves while Foundry is closed.
        tracker = _RoundOnly(round_counter=7)
        self.assertEqual(tracker.apply(_snapshot(active=False, round_value=0)), 7)

    def test_inactive_combat_with_a_real_round_is_still_ignored(self):
        tracker = _RoundOnly(round_counter=7)
        self.assertEqual(tracker.apply(_snapshot(active=False, round_value=3)), 7)

    def test_an_active_combat_is_authoritative(self):
        tracker = _RoundOnly(round_counter=7)
        self.assertEqual(tracker.apply(_snapshot(active=True, round_value=4)), 4)

    def test_an_active_combat_reporting_round_zero_is_ignored(self):
        # Foundry reports 0 between "combat created" and "combat started".
        tracker = _RoundOnly(round_counter=7)
        self.assertEqual(tracker.apply(_snapshot(active=True, round_value=0)), 7)

    def test_a_missing_round_is_ignored(self):
        tracker = _RoundOnly(round_counter=7)
        snapshot = _snapshot(active=True, round_value=0)
        del snapshot["combat"]["round"]
        self.assertEqual(tracker.apply(snapshot), 7)

    def test_the_shipped_rule_matches_this_one(self):
        """Guard against the app and this test drifting apart."""
        source = (REPO_ROOT / "lib" / "app" / "app.py").read_text()
        self.assertIn("and combat.get(\"active\")", source)
        self.assertIn("and round_value >= 1", source)


if __name__ == "__main__":
    unittest.main()
