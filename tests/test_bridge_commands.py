"""Bridge commands must not block the GUI thread, and must arrive in order.

The regression this guards: _post_command used to POST inline, so every turn
change waited on a round trip to the bridge before the table could repaint --
~460ms against a remote bridge, which is the entire delay between pressing
Next and seeing anything happen.
"""
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lib"))

from app.bridge_client import BridgeClient  # noqa: E402

RESPONSE_DELAY = 0.05


class _Recorder(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        time.sleep(RESPONSE_DELAY)          # stand in for a remote bridge
        type(self).received.append(body.get("type"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class BridgeCommandDeliveryTests(unittest.TestCase):
    def setUp(self):
        _Recorder.received = []
        TCPServer.allow_reuse_address = True
        self.server = TCPServer(("127.0.0.1", 0), _Recorder)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client = BridgeClient(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            token="test-token",
            timeout_s=5,
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_sending_does_not_wait_for_the_bridge(self):
        started = time.perf_counter()
        for _ in range(6):
            self.client.send_next_turn()
        elapsed = time.perf_counter() - started
        # Six inline POSTs would take at least 6 * RESPONSE_DELAY.
        self.assertLess(elapsed, 6 * RESPONSE_DELAY / 2)

    def test_every_command_is_delivered(self):
        for _ in range(6):
            self.client.send_next_turn()
        self.client.flush_commands(timeout=10)
        self.assertEqual(len(_Recorder.received), 6)

    def test_commands_arrive_in_the_order_they_were_sent(self):
        self.client.send_next_turn()
        self.client.enqueue_set_hp("Goblin", 5)
        self.client.send_prev_turn()
        self.client.send_next_turn()
        self.client.flush_commands(timeout=10)
        self.assertEqual(
            _Recorder.received,
            ["next_turn", "set_hp", "prev_turn", "next_turn"],
        )

    def test_a_disabled_client_sends_nothing(self):
        mute = BridgeClient(base_url=self.client.base_url, token="", timeout_s=1)
        self.assertFalse(mute.send_next_turn())
        mute.flush_commands(timeout=1)
        self.assertEqual(_Recorder.received, [])


class BridgeUnreachableTests(unittest.TestCase):
    def test_an_unreachable_bridge_still_returns_immediately(self):
        # Port 1 refuses instantly; the point is that the caller never waits.
        client = BridgeClient(base_url="http://127.0.0.1:1", token="t", timeout_s=1)
        started = time.perf_counter()
        client.send_next_turn()
        client.send_next_turn()
        self.assertLess(time.perf_counter() - started, 0.5)
        client.flush_commands(timeout=3)


if __name__ == "__main__":
    unittest.main()
