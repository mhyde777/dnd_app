# lib/app/foundry_socket_client.py
"""
Direct Foundry VTT socket.io client.

Connects to a remote Foundry server as an authenticated user (outbound
connection -- no tunnel or bridge service required).  Implements the same
public interface as BridgeClient so app.py can swap the two transparently.

Protocol (module event name: "module.foundryvtt-bridge"):
  Python -> Foundry:  {type: "command",      command: {type, id, payload}}
  Python -> Foundry:  {type: "get_snapshot"}   <- request an immediate snapshot
  Foundry -> Python:  {type: "snapshot",     data: <combat snapshot dict>}
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
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


def _find_user_id(html: str, username: str) -> Tuple[Optional[str], List[Tuple[str, str]]]:
    """
    Return (user_id, all_users) where user_id matches *username* (or None).
    Returns all_users so callers can show a helpful error.
    """
    parser = _JoinPageParser()
    parser.feed(html)
    lower = username.strip().lower()
    for uid, label in parser.users:
        if label.lower() == lower:
            return uid, parser.users
    # Fallback: prefer Gamemaster
    for uid, label in parser.users:
        if "gamemaster" in label.lower() or "game master" in label.lower():
            return uid, parser.users
    if parser.users:
        return parser.users[0][0], parser.users
    return None, parser.users


# ---------------------------------------------------------------------------
# Diagnostic result
# ---------------------------------------------------------------------------

@dataclass
class ConnectionTestResult:
    reachable: bool = False
    users_found: List[str] = field(default_factory=list)
    user_id_found: bool = False
    login_ok: bool = False
    socket_connected: bool = False
    error: str = ""

    def summary(self) -> str:
        lines = []
        lines.append(f"{'OK' if self.reachable else 'FAIL'}  Reach Foundry /join page")
        if self.users_found:
            lines.append(f"      Users found: {', '.join(self.users_found)}")
        lines.append(f"{'OK' if self.user_id_found else 'FAIL'}  Find configured username in user list")
        lines.append(f"{'OK' if self.login_ok else 'FAIL'}  Login (POST /join)")
        lines.append(f"{'OK' if self.socket_connected else 'FAIL'}  Socket.io connection")
        if self.error:
            lines.append(f"\nError: {self.error}")
        return "\n".join(lines)


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
                ok, result = self._login_verbose()
                if not ok:
                    print(f"[FoundrySocket] Login failed ({result}) -- retrying in {retry_delay}s")
                    stop_event.wait(retry_delay)
                    continue

                self._connect_socket(on_snapshot)
                if not self._connected:
                    print("[FoundrySocket] Socket connection failed -- retrying")
                    stop_event.wait(retry_delay)
                    continue

                # Request an immediate snapshot
                self._emit_raw({"type": "get_snapshot"})

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

    def test_connection(self) -> ConnectionTestResult:
        """
        Run a step-by-step connection test and return a structured result.
        Safe to call from any thread; uses a fresh HTTP session.
        """
        result = ConnectionTestResult()
        http = requests.Session()
        join_url = f"{self.foundry_url}/join"

        # Step 1: reach /join
        try:
            resp = http.get(join_url, timeout=self.timeout)
            resp.raise_for_status()
            result.reachable = True
        except Exception as exc:
            result.error = f"Cannot reach {join_url}: {exc}"
            return result

        # Step 2: find user
        user_id, all_users = _find_user_id(resp.text, self.username)
        result.users_found = [label for _, label in all_users]
        if not user_id:
            result.error = (
                f"Username '{self.username}' not found on /join page. "
                f"Available users: {result.users_found or ['(none — is the world running?)']}"
            )
            return result
        result.user_id_found = True

        # Step 3: login
        try:
            resp = http.post(
                join_url,
                data={"userid": user_id, "password": self.password},
                timeout=self.timeout,
                allow_redirects=True,
            )
            if "/join" in resp.url and "password" in resp.text.lower():
                result.error = "Login rejected -- wrong password."
                return result
            if not http.cookies:
                result.error = (
                    "Login seemed to succeed but no session cookie was set. "
                    "This may indicate an unexpected Foundry version or auth flow."
                )
                return result
            result.login_ok = True
        except Exception as exc:
            result.error = f"POST /join failed: {exc}"
            return result

        # Step 4: socket.io connection
        cookie_header = "; ".join(f"{c.name}={c.value}" for c in http.cookies)
        headers = {"Cookie": cookie_header} if cookie_header else {}
        connected_event = threading.Event()

        client = sio_lib.Client(logger=False, engineio_logger=False, reconnection=False)

        @client.on("connect")
        def _on_connect():
            connected_event.set()

        try:
            client.connect(
                self.foundry_url,
                headers=headers,
                wait_timeout=self.timeout,
            )
            connected_event.wait(timeout=self.timeout)
            result.socket_connected = client.connected
            if not result.socket_connected:
                result.error = "Socket.io connected but immediately dropped."
        except Exception as exc:
            result.error = f"Socket.io connection failed: {exc}"
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

        return result

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

    def _login_verbose(self) -> Tuple[bool, str]:
        """Login and return (success, error_message)."""
        join_url = f"{self.foundry_url}/join"
        try:
            resp = self._http.get(join_url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as exc:
            return False, f"GET /join failed: {exc}"

        user_id, all_users = _find_user_id(resp.text, self.username)
        labels = [label for _, label in all_users]
        print(f"[FoundrySocket] /join users found: {labels}")
        if not user_id:
            return False, (
                f"User '{self.username}' not found. "
                f"Available: {labels or ['(none -- is the world running?)']}"
            )

        try:
            resp = self._http.post(
                join_url,
                data={"userid": user_id, "password": self.password},
                timeout=self.timeout,
                allow_redirects=True,
            )
            cookies = list(self._http.cookies.keys())
            print(f"[FoundrySocket] POST /join -> {resp.url}  cookies={cookies}")
            if "/join" in resp.url and "password" in resp.text.lower():
                return False, "Wrong password"
            print(f"[FoundrySocket] Logged in as '{self.username}' (id={user_id})")
            return True, ""
        except Exception as exc:
            return False, f"POST /join failed: {exc}"

    def _connect_socket(self, on_snapshot: Callable[[Dict[str, Any]], None]) -> None:
        """Create and connect a socket.io client."""
        cookie_header = "; ".join(
            f"{c.name}={c.value}" for c in self._http.cookies
        )
        print(f"[FoundrySocket] Connecting socket.io to {self.foundry_url} ...")

        client = sio_lib.Client(logger=False, engineio_logger=False, reconnection=False)
        self._sio = client

        @client.on("connect")
        def _on_connect():
            self._connected = True
            print(f"[FoundrySocket] Socket connected")

        @client.on("disconnect")
        def _on_disconnect():
            self._connected = False
            print("[FoundrySocket] Socket disconnected")

        @client.on("connect_error")
        def _on_connect_error(data):
            print(f"[FoundrySocket] Socket connect_error: {data}")

        @client.on("world")
        def _on_world(data):
            print("[FoundrySocket] Received 'world' event (Foundry world loaded)")

        @client.on(self.EVENT_NAME)
        def _on_module_event(data):
            if not isinstance(data, dict):
                return
            if data.get("type") == "snapshot":
                snapshot = data.get("data")
                if isinstance(snapshot, dict):
                    print(f"[FoundrySocket] Snapshot received ({len(snapshot.get('combatants', []))} combatants)")
                    with self._snapshot_lock:
                        self._last_snapshot = snapshot
                    on_snapshot(snapshot)

        headers = {"Cookie": cookie_header} if cookie_header else {}
        try:
            # Let python-socketio negotiate transport (polling -> websocket upgrade)
            # rather than forcing websocket-only, which can fail behind proxies.
            client.connect(
                self.foundry_url,
                headers=headers,
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
