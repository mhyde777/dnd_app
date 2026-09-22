"""The bridge indicator must distinguish "reachable" from "receiving snapshots".

`/state` answers `{}` with a 200 until Foundry posts for the first time. That
used to land on "connected" (green), so a world where the Combat Tracker module
was never enabled -- the usual case after starting a new one-shot -- looked
exactly like a healthy sync. Since the in-process bridge became the default it
is always reachable, so green from launch meant nothing at all.
"""

import importlib.util
import os
import sys
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PYQT_AVAILABLE = importlib.util.find_spec("PyQt5") is not None

if PYQT_AVAILABLE:
    REPO_ROOT = Path(__file__).resolve().parents[1]
    LIB_DIR = REPO_ROOT / "lib"
    sys.path.insert(0, str(LIB_DIR))

    from app.app import Application


class _StatusRecorder:
    """Enough of Application for the empty-snapshot path, and nothing more."""

    _snapshot_is_from_foundry = staticmethod(
        Application._snapshot_is_from_foundry if PYQT_AVAILABLE else None
    )

    def __init__(self):
        self.statuses = []

    def set_bridge_status(self, state):
        self.statuses.append(state)


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt5 not installed")
class SnapshotIsFromFoundryTests(unittest.TestCase):
    def test_empty_snapshot_is_not_from_foundry(self):
        """What the bridge serves before Foundry has ever posted."""
        self.assertFalse(Application._snapshot_is_from_foundry({}))

    def test_world_key_counts(self):
        self.assertTrue(Application._snapshot_is_from_foundry({"world": "Curse of Strahd"}))

    def test_idle_world_with_no_combat_still_counts(self):
        """Foundry open, no encounter running, is connected -- not waiting."""
        snapshot = {"world": "Test", "combat": {"active": False, "round": 0}, "combatants": []}
        self.assertTrue(Application._snapshot_is_from_foundry(snapshot))

    def test_blank_world_name_still_counts(self):
        """Presence of the key is the signal, not its value."""
        self.assertTrue(Application._snapshot_is_from_foundry({"world": ""}))

    def test_combatants_alone_counts(self):
        self.assertTrue(Application._snapshot_is_from_foundry({"combatants": []}))


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt5 not installed")
class SetBridgeSnapshotStatusTests(unittest.TestCase):
    def test_empty_snapshot_reports_waiting(self):
        recorder = _StatusRecorder()
        Application._set_bridge_snapshot(recorder, {})
        self.assertEqual(recorder.statuses, ["waiting"])

    def test_none_snapshot_sets_no_status(self):
        """None is the fetch-failed path; _deliver_bridge_snapshot owns it."""
        recorder = _StatusRecorder()
        Application._set_bridge_snapshot(recorder, None)
        self.assertEqual(recorder.statuses, [])

    def test_non_dict_snapshot_sets_no_status(self):
        recorder = _StatusRecorder()
        Application._set_bridge_snapshot(recorder, ["not", "a", "dict"])
        self.assertEqual(recorder.statuses, [])


if __name__ == "__main__":
    unittest.main()
