"""The app must never overwrite a PC's HP in Foundry with a stale number.

The regression: coming back to a session, PC tokens in Foundry had their HP
reset to some earlier value. Three things made that possible, and each has a
guard here:

1. Foundry token/actor ids are saved with the game state, so a creature loaded
   from last session's save could push HP before Foundry had sent the app a
   single number -- and that HP was whatever it was when the save was written.
2. HP commands carried only an absolute value, so any drift between the app
   and Foundry was resolved by throwing Foundry's value away.
3. The bridge queue handed Foundry expired commands: the sweeper removed one
   per tick, and the command stream sends the whole backlog on reconnect.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lib"))
sys.path.insert(0, str(REPO_ROOT))

from bridge_service.command_queue import CommandQueue  # noqa: E402
from app.bridge_client import BridgeClient  # noqa: E402
from app.app import Application  # noqa: E402


def _ts(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class ExpiredCommandsAreNeverDeliveredTests(unittest.TestCase):
    def _queue(self):
        q = CommandQueue(max_age_seconds=60)
        q.put({"id": "old-1", "type": "set_hp", "timestamp": _ts(600)})
        q.put({"id": "old-2", "type": "set_hp", "timestamp": _ts(300)})
        q.put({"id": "fresh", "type": "set_hp", "timestamp": _ts(1)})
        return q

    def test_the_stream_backlog_excludes_expired_commands(self):
        self.assertEqual([c["id"] for c in self._queue().get_all()], ["fresh"])

    def test_polling_skips_past_expired_commands(self):
        q = self._queue()
        self.assertEqual(q.pop_next()["id"], "fresh")
        self.assertIsNone(q.pop_next())

    def test_one_sweep_removes_every_expired_command_not_just_the_head(self):
        q = CommandQueue()  # no max age: only the explicit sweep is in play
        q.put({"id": "fresh", "type": "x", "timestamp": _ts(1)})
        q.put({"id": "old", "type": "x", "timestamp": _ts(600)})
        q.max_age_seconds = 60
        swept = q.sweep_expired()
        self.assertEqual([c["id"] for c in swept], ["old"])
        self.assertEqual([c["id"] for c in q.items], ["fresh"])

    def test_a_persisted_queue_drops_expired_commands_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "commands.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    [
                        {"id": "last-session", "type": "set_hp", "timestamp": _ts(86400)},
                        {"id": "fresh", "type": "set_hp", "timestamp": _ts(1)},
                    ],
                    handle,
                )
            q = CommandQueue(persist_path=path, max_age_seconds=60)
            q.load()
            self.assertEqual([c["id"] for c in q.items], ["fresh"])


class _RecordingClient:
    enabled = True

    def __init__(self):
        self.sent = []

    def enqueue_set_hp(self, **kwargs):
        self.sent.append(("set_hp", kwargs))

    def enqueue_set_temp_hp(self, **kwargs):
        self.sent.append(("set_temp_hp", kwargs))

    def enqueue_set_max_hp_bonus(self, **kwargs):
        self.sent.append(("set_max_hp_bonus", kwargs))


class _App:
    """Just enough of Application to drive the HP push methods."""

    _bridge_hp_synced_names = Application._bridge_hp_synced_names
    _bridge_hp_push_allowed = Application._bridge_hp_push_allowed
    _enqueue_bridge_set_hp = Application._enqueue_bridge_set_hp
    _enqueue_bridge_set_temp_hp = Application._enqueue_bridge_set_temp_hp
    _enqueue_bridge_set_max_hp_bonus = Application._enqueue_bridge_set_max_hp_bonus

    def __init__(self):
        self.bridge_client = _RecordingClient()
        self.logged = []

    def _bridge_token_target(self, name):
        # Ids restored from a save: addressable, but nothing synced yet.
        return ("tok-" + name, "act-" + name)

    def _log(self, message):
        self.logged.append(message)


class AppWithholdsUnsyncedHpTests(unittest.TestCase):
    def test_hp_is_not_pushed_before_foundry_has_synced_the_creature(self):
        app = _App()
        app._enqueue_bridge_set_hp("Aria", 12, expected_hp=20)
        app._enqueue_bridge_set_temp_hp("Aria", 5)
        app._enqueue_bridge_set_max_hp_bonus("Aria", 5, expected_bonus=0)
        self.assertEqual(app.bridge_client.sent, [])
        self.assertTrue(any("not been synced" in m for m in app.logged))

    def test_hp_is_pushed_with_its_expected_value_once_synced(self):
        app = _App()
        app._bridge_hp_synced_names().add("Aria")
        app._enqueue_bridge_set_hp("Aria", 12, expected_hp=20)
        app._enqueue_bridge_set_max_hp_bonus("Aria", 5, expected_bonus=0)
        (kind, hp), (kind2, bonus) = app.bridge_client.sent
        self.assertEqual((kind, hp["hp"], hp["expected_hp"]), ("set_hp", 12, 20))
        self.assertEqual(
            (kind2, bonus["max_hp_bonus"], bonus["expected_tempmax"]),
            ("set_max_hp_bonus", 5, 0),
        )


class PayloadCarriesExpectedValueTests(unittest.TestCase):
    def test_expected_rides_in_the_payload(self):
        client = BridgeClient(base_url="http://127.0.0.1:1", token="t")
        captured = {}
        client._post_command = lambda **kw: captured.update(kw) or True
        client.enqueue_set_hp("tok", 12, actor_id="act", expected_hp=20)
        self.assertEqual(
            captured["payload"], {"tokenId": "tok", "hp": 12, "expected": 20, "actorId": "act"}
        )

    def test_no_expected_key_when_the_caller_did_not_give_one(self):
        client = BridgeClient(base_url="http://127.0.0.1:1", token="t")
        captured = {}
        client._post_command = lambda **kw: captured.update(kw) or True
        client.enqueue_set_hp("tok", 12)
        self.assertNotIn("expected", captured["payload"])


if __name__ == "__main__":
    unittest.main()
