import unittest
from datetime import datetime, timedelta, timezone

from bridge_service.command_queue import CommandQueue


class CommandQueueSweeperTests(unittest.TestCase):
    def test_sweeper_removes_expired_head(self):
        queue = CommandQueue()
        now = datetime.now(timezone.utc)
        old_timestamp = (now - timedelta(seconds=120)).isoformat()
        fresh_timestamp = (now - timedelta(seconds=10)).isoformat()

        queue.put({"id": "cmd-old", "type": "test", "timestamp": old_timestamp})
        queue.put({"id": "cmd-new", "type": "test", "timestamp": fresh_timestamp})

        swept = queue.sweep_head_if_expired(60)
        self.assertIsNotNone(swept)
        cmd, age_seconds = swept
        self.assertEqual(cmd["id"], "cmd-old")
        self.assertGreater(age_seconds, 60)
        self.assertEqual(queue.get_next()["id"], "cmd-new")


if __name__ == "__main__":
    unittest.main()
