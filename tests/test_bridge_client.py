import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "lib"
sys.path.insert(0, str(LIB_DIR))

from app.bridge_client import _build_set_hp_payload


class BridgeClientPayloadTests(unittest.TestCase):
    def test_build_set_hp_payload_optional_fields(self):
        payload = _build_set_hp_payload(
            token_id="token-123",
            hp=12,
            actor_id="actor-456",
            command_id="cmd-789",
        )
        self.assertEqual(payload["source"], "app")
        self.assertEqual(payload["type"], "set_hp")
        self.assertEqual(payload["tokenId"], "token-123")
        self.assertEqual(payload["hp"], 12)
        self.assertEqual(payload["actorId"], "actor-456")
        self.assertEqual(payload["id"], "cmd-789")

    def test_build_set_hp_payload_minimum_fields(self):
        payload = _build_set_hp_payload(
            token_id="token-123",
            hp=5,
        )
        self.assertEqual(payload["source"], "app")
        self.assertEqual(payload["type"], "set_hp")
        self.assertEqual(payload["tokenId"], "token-123")
        self.assertEqual(payload["hp"], 5)
        self.assertNotIn("actorId", payload)
        self.assertNotIn("id", payload)


if __name__ == "__main__":
    unittest.main()
