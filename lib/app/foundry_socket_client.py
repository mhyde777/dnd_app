# lib/app/foundry_socket_client.py
"""
Direct Foundry VTT socket.io client.

Connects to a remote Foundry server as an authenticated user (outbound
connection — no tunnel or bridge service required).  Implements the same
public interface as BridgeClient so app.py can swap the two transparently.

Protocol (module event name: "module.foundryvtt-bridge"):
  Python -> Foundry:  {type: "command",      command: {type, id, payload}}
  Python -> Foundry:  {type: "get_snapshot"}   <- request an immediate snapshot
  Foundry -> Python:  {type: "snapshot",     data: <combat snapshot dict>}
"""
from __future__ import annotations

import threading
import time
import uuid
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
import socketio as sio_lib


# ---------------------------------------------------------------------------
# HTML parser -- finds userid/username pairs from Foundry's /join page
# ---------------------------------------------------------------------------

class _JoinPageParser(HTMLParser):
    """Extracts (value, label) pairs for the 'userid' field on /join."""

    def __init__(self) -> None:
        super().__init__()
        self.users: List[Tuple[str, str]] = []
        self._in_select = False
        self._in_option = False
        self._current_value: str = ""
        self._current_text: str = ""
        self._pending_radio_value: str = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr = dict(attrs)
        name = attr.get("name", "")

        if tag == "select" and name == "userid":
            self._in_select = True

        if self._in_select and tag == "option":
            self._in_option = True
            self._current_value = attr.get("value", "")
            self._current_text = ""

        if tag == "input" and attr.get("type") == "radio" and name == "userid":
            self._pending_radio_value = attr.get("value", "")

        if tag == "label" and self._pending_radio_value:
            self._current_value = self._pending_radio_value
            self._in_option = True
            self._current_text = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._in_select = False
        if self._in_option and tag in ("option", "label"):
            if self._current_value and self._current_text.strip():
                self.users.append((self._current_value, self._current_text.strip()))
            self._in_option = False
            self._pending_radio_value = ""

    def handle_data(self, data: str) -> None:
        if self._in_option:
            self._current_text += data


def _find_user_id(html: str, username: str) -> Optional[str]:
    """Return the Foundry user ID whose display name matches *username*."""
    parser = _JoinPageParser()
    parser.feed(html)
    lower = username.strip().lower()
    for uid, label in parser.users:
        if label.lower() == lower:
            return uid
    # Fallback: single-user worlds often have only one entry
    for uid, label in parser.users:
        if "gamemaster" in label.lower() or "game master" in label.lower():
            return uid
    if parser.users:
        return parser.users[0][0]
    return None


# ---------------------------------------------------------------------------
# FoundrySocketClient
# ---------------------------------------------------------------------------

class FoundrySocketClient:
    """
    Drop-in replacement for BridgeClient that talks directly to Foundry
    via socket.io -- no bridge service or tunnel required.
    """

    MODULE_ID = "foundryvtt-bridge"
    EVENT_NAME = f"module.{MODULE_ID}"

    def __init__(
        self,
        foundry_url: str,
        username: str,
        password: str = "",
        timeout: float = 10.0,
    ) -> None:
        self.foundry_url = foundry_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

        self._http = requests.Session()
        self._sio: Optional[sio_lib.Client] = None
        self._connected = False
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._snapshot_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface (mirrors BridgeClient)
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.foundry_url and self.username)

    def fetch_state(self) -> Optional[Dict[str, Any]]:
        """Return the most recently received snapshot (non-blocking)."""
        with self._snapshot_lock:
            return self._last_snapshot

    def stream_state(
        self,
        on_snapshot: Callable[[Dict[str, Any]], None],
        stop_event: threading.Event,
    ) -> None:
        """
        Connect to Foundry and deliver snapshots to *on_snapshot*.
        Runs in a background thread; retries on disconnect.
        """
        retry_delay = 5.0
        while not stop_event.is_set():
            try:
                if not self._login():
                    print(f"[FoundrySocket] Login failed -- retrying in {retry_delay}s")
                    stop_event.wait(retry_delay)
                    continue

                self._connect_socket(on_snapshot)
                if not self._connected:
                    print("[FoundrySocket] Socket connection failed -- retrying")
                    stop_event.wait(retry_delay)
                    continue

                # Request an immediate snapshot so we don't wait for the next event
                self._emit_raw({"type": "get_snapshot"})

                # Block until stop requested or socket drops
                while not stop_event.is_set() and self._connected:
                    stop_event.wait(1.0)

                if stop_event.is_set():
                    break

                print(f"[FoundrySocket] Disconnected -- retrying in {retry_delay}s")
                stop_event.wait(retry_delay)

            except Exception as exc:
                print(f"[FoundrySocket] Error: {exc}")
                stop_event.wait(retry_delay)

        self._disconnect()

    # Command senders -- same signatures as BridgeClient

    def enqueue_set_hp(
        self,
        token_id: str,
        hp: int,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload: Dict[str, Any] = {"tokenId": token_id, "hp": int(hp)}
        if actor_id:
            payload["actorId"] = actor_id
        return self._send_command("set_hp", payload, command_id)

    def enqueue_set_temp_hp(
        self,
        token_id: str,
        temp_hp: int,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload: Dict[str, Any] = {"tokenId": token_id, "temp": int(temp_hp)}
        if actor_id:
            payload["actorId"] = actor_id
        return self._send_command("set_temp_hp", payload, command_id)

    def enqueue_set_max_hp_bonus(
        self,
        token_id: str,
        max_hp_bonus: int,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload: Dict[str, Any] = {"tokenId": token_id, "tempmax": int(max_hp_bonus)}
        if actor_id:
            payload["actorId"] = actor_id
        return self._send_command("set_max_hp_bonus", payload, command_id)

    def send_set_initiative(
        self,
        initiative: int,
        combatant_id: Optional[str] = None,
        token_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload: Dict[str, Any] = {"initiative": initiative}
        if combatant_id:
            payload["combatantId"] = combatant_id
        if token_id:
            payload["tokenId"] = token_id
        if actor_id:
            payload["actorId"] = actor_id
        return self._send_command("set_initiative", payload, command_id)

    def send_add_condition(
        self,
        effect_id: Optional[str] = None,
        label: Optional[str] = None,
        token_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload: Dict[str, Any] = {}
        if effect_id:
            payload["effectId"] = effect_id
        if label:
            payload["label"] = label
        if token_id:
            payload["tokenId"] = token_id
        if actor_id:
            payload["actorId"] = actor_id
        return self._send_command("add_condition", payload, command_id)

    def send_remove_condition(
        self,
        effect_id: Optional[str] = None,
        label: Optional[str] = None,
        token_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload: Dict[str, Any] = {}
        if effect_id:
            payload["effectId"] = effect_id
        if label:
            payload["label"] = label
        if token_id:
            payload["tokenId"] = token_id
        if actor_id:
            payload["actorId"] = actor_id
        return self._send_command("remove_condition", payload, command_id)

    def send_next_turn(self, command_id: Optional[str] = None) -> bool:
        return self._send_command("next_turn", {}, command_id)

    def send_prev_turn(self, command_id: Optional[str] = None) -> bool:
        return self._send_command("prev_turn", {}, command_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _login(self) -> bool:
        """Fetch /join, find the user ID, POST credentials, get session cookie."""
        join_url = f"{self.foundry_url}/join"
        try:
            resp = self._http.get(join_url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as exc:
            print(f"[FoundrySocket] GET /join failed: {exc}")
            return False

        user_id = _find_user_id(resp.text, self.username)
        if not user_id:
            print(
                f"[FoundrySocket] Could not find user '{self.username}' on /join page. "
                "Check that the username is correct and the world is running."
            )
            return False

        try:
            resp = self._http.post(
                join_url,
                data={"userid": user_id, "password": self.password},
                timeout=self.timeout,
                allow_redirects=True,
            )
            # Foundry redirects to /game on success; landing back on /join
            # with a password field usually means wrong credentials.
            if "/join" in resp.url and "password" in resp.text.lower():
                print("[FoundrySocket] Login rejected -- check username/password.")
                return False
            print(f"[FoundrySocket] Logged in as '{self.username}' (id={user_id})")
            return True
        except Exception as exc:
            print(f"[FoundrySocket] POST /join failed: {exc}")
            return False

    def _connect_socket(self, on_snapshot: Callable[[Dict[str, Any]], None]) -> None:
        """Create and connect a socket.io client."""
        cookie_header = "; ".join(
            f"{c.name}={c.value}" for c in self._http.cookies
        )

        client = sio_lib.Client(logger=False, engineio_logger=False, reconnection=False)
        self._sio = client

        @client.on("connect")
        def _on_connect():
            self._connected = True
            print(f"[FoundrySocket] Socket connected to {self.foundry_url}")

        @client.on("disconnect")
        def _on_disconnect():
            self._connected = False
            print("[FoundrySocket] Socket disconnected")

        @client.on("world")
        def _on_world(data):
            print("[FoundrySocket] World event received (world is ready)")

        @client.on(self.EVENT_NAME)
        def _on_module_event(data):
            if not isinstance(data, dict):
                return
            if data.get("type") == "snapshot":
                snapshot = data.get("data")
                if isinstance(snapshot, dict):
                    with self._snapshot_lock:
                        self._last_snapshot = snapshot
                    on_snapshot(snapshot)

        headers = {"Cookie": cookie_header} if cookie_header else {}
        try:
            client.connect(
                self.foundry_url,
                headers=headers,
                transports=["websocket"],
                wait_timeout=self.timeout,
            )
        except Exception as exc:
            print(f"[FoundrySocket] socket.io connect failed: {exc}")
            self._connected = False

    def _disconnect(self) -> None:
        if self._sio and self._connected:
            try:
                self._sio.disconnect()
            except Exception:
                pass
        self._connected = False
        self._sio = None

    def _emit_raw(self, data: Dict[str, Any]) -> bool:
        if not self._sio or not self._connected:
            return False
        try:
            self._sio.emit(self.EVENT_NAME, data)
            return True
        except Exception as exc:
            print(f"[FoundrySocket] emit error: {exc}")
            return False

    def _send_command(
        self,
        cmd_type: str,
        payload: Dict[str, Any],
        command_id: Optional[str] = None,
    ) -> bool:
        if not self.enabled:
            print("[FoundrySocket] Not configured; skipping command.")
            return False
        cmd: Dict[str, Any] = {
            "id": command_id or str(uuid.uuid4()),
            "type": cmd_type,
            "payload": payload,
        }
        result = self._emit_raw({"type": "command", "command": cmd})
        if result:
            print(f"[FoundrySocket] Sent command type={cmd_type}")
        else:
            print(f"[FoundrySocket] Could not send command type={cmd_type} -- not connected")
        return result
