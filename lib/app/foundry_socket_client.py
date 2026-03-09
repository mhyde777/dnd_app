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

import json
import re
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
    Handles both HTML select/radio forms and JSON-embedded user data.
    """
    # Strategy 1: standard HTML select/radio parser
    parser = _JoinPageParser()
    parser.feed(html)
    users = parser.users

    # Strategy 2: JSON embedded in a <script> tag
    # Foundry v12 embeds users as: users: [{"_id":..., "name":...}, ...]
    if not users:
        for m in re.finditer(r'"users"\s*:\s*(\[.*?\])', html, re.DOTALL):
            try:
                parsed = json.loads(m.group(1))
                users = [(u["_id"], u.get("name", u.get("_id", "")))
                         for u in parsed if "_id" in u]
                if users:
                    break
            except Exception:
                pass

    # Strategy 3: data-user-id attributes (some Foundry themes)
    if not users:
        for m in re.finditer(r'data-user-id=(["\'])(.*?)\1[^>]*>([^<]+)<', html):
            users.append((m.group(1), m.group(2).strip()))

    lower = username.strip().lower()
    for uid, label in users:
        if label.lower() == lower:
            return uid, users
    for uid, label in users:
        if "gamemaster" in label.lower() or "game master" in label.lower():
            return uid, users
    if users:
        return users[0][0], users
    return None, users


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
        user_id: str = "",
        timeout: float = 10.0,
    ) -> None:
        self.foundry_url = foundry_url.rstrip("/")
        self.username = username
        self.password = password
        self.user_id = user_id.strip()
        self.timeout = timeout

        self._http = requests.Session()
        # Mimic a real browser so Foundry's session middleware treats us the same way
        self._http.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
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
        if self.user_id:
            user_id = self.user_id
            result.user_id_found = True
            result.users_found = [f"(provided directly: {user_id})"]
        else:
            user_id_found, all_users = _find_user_id(resp.text, self.username)
            result.users_found = [label for _, label in all_users]
            if not user_id_found:
                html = resp.text
                idx = html.lower().find("userid")
                if idx == -1:
                    idx = html.lower().find("user")
                snippet = ""
                if idx != -1:
                    snippet = "\n\nHTML near 'user':\n" + html[max(0, idx-100):idx+300].strip()
                else:
                    snippet = "\n\nFirst 400 chars of /join page:\n" + html[:400].strip()
                result.error = (
                    f"Username '{self.username}' not found on /join page "
                    f"(found: {result.users_found or ['none']}).\n"
                    "For Foundry v13+, open the Foundry browser console (F12) and "
                    "type game.userId — paste that value into the User ID field in Settings."
                    + snippet
                )
                return result
            user_id = user_id_found
            result.user_id_found = True

        # Step 3: login
        login_ok = False
        for post_kwargs in [
            dict(json={"action": "join", "userid": user_id, "password": self.password}),
            dict(data={"userid": user_id, "password": self.password}),
        ]:
            try:
                resp = http.post(join_url, timeout=self.timeout, allow_redirects=True, **post_kwargs)
                is_error = any(e in resp.text for e in ("ErrorUser", "ErrorPassword", "Error"))
                if resp.status_code in (200, 302) and not is_error:
                    login_ok = True
                    break
                if "ErrorPassword" in resp.text:
                    result.error = "Login rejected — wrong password."
                    return result
                if "ErrorUser" in resp.text:
                    result.error = f"Login rejected — user ID not found: {resp.text.strip()}"
                    return result
            except Exception as exc:
                result.error = f"POST /join failed: {exc}"
                return result
        if not login_ok:
            result.error = f"Login did not succeed (last response: {resp.status_code} {resp.text[:120]!r})"
            return result
        if not http.cookies:
            result.error = "Login seemed to succeed but no session cookie was set."
            return result
        result.login_ok = True

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

        # --- Resolve user ID ---
        if self.user_id:
            # User provided UUID directly (required for Foundry v13+)
            user_id = self.user_id
            print(f"[FoundrySocket] Using provided user ID: {user_id}")
        else:
            # Older Foundry: parse HTML /join page for the user list
            try:
                resp = self._http.get(join_url, timeout=self.timeout)
                resp.raise_for_status()
            except Exception as exc:
                return False, f"GET /join failed: {exc}"
            user_id_found, all_users = _find_user_id(resp.text, self.username)
            labels = [label for _, label in all_users]
            print(f"[FoundrySocket] /join users found: {labels}")
            if not user_id_found:
                return False, (
                    f"User '{self.username}' not found on /join page "
                    f"(found: {labels or ['none']}). "
                    "For Foundry v13+, open the browser console in Foundry and "
                    "type game.userId to get your User ID, then enter it in Settings."
                )
            user_id = user_id_found

        # --- POST login ---
        # Try form POST first (what browsers actually send — sets session.userId properly
        # in Express-session). Fall back to JSON API if form POST doesn't work.
        for post_kwargs in [
            dict(data={"userid": user_id, "password": self.password}),
            dict(json={"action": "join", "userid": user_id, "password": self.password}),
        ]:
            try:
                resp = self._http.post(
                    join_url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    **post_kwargs,
                )
                cookies = list(self._http.cookies.keys())
                print(f"[FoundrySocket] POST /join -> {resp.status_code} {resp.url}  cookies={cookies}  body={resp.text[:120]!r}")
                is_error = any(e in resp.text for e in ("ErrorUser", "ErrorPassword"))
                if resp.status_code in (200, 302) and not is_error:
                    # Foundry v13 returns JSON with a redirect URL.
                    # We must GET that URL (/game) to move the session from
                    # the lobby into the world context — otherwise the socket.io
                    # server treats us as unauthenticated (session event = null).
                    redirect_path = "/game"
                    try:
                        body = resp.json()
                        redirect_path = body.get("redirect", redirect_path)
                    except Exception:
                        pass
                    game_url = f"{self.foundry_url}{redirect_path}"
                    try:
                        gr = self._http.get(game_url, timeout=self.timeout, allow_redirects=True)
                        print(
                            f"[FoundrySocket] GET {redirect_path} -> {gr.status_code} {gr.url}"
                            f"  cookies={list(self._http.cookies.keys())}"
                            f"  body={gr.text[:80]!r}"
                        )
                    except Exception as exc:
                        print(f"[FoundrySocket] Warning: GET {redirect_path} failed: {exc}")
                    print(f"[FoundrySocket] Logged in as '{self.username}' (id={user_id})")
                    return True, ""
                if is_error:
                    return False, f"Login rejected: {resp.text.strip()}"
            except Exception as exc:
                return False, f"POST /join failed: {exc}"

        return False, "Login did not succeed with any format."

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
        def _on_disconnect(reason=None):
            self._connected = False
            print(f"[FoundrySocket] Socket disconnected (reason={reason!r})")

        @client.on("connect_error")
        def _on_connect_error(data):
            print(f"[FoundrySocket] Socket connect_error: {data}")

        @client.on("session")
        def _on_session(data):
            print(f"[FoundrySocket] Session event: {str(data)[:300]}")

        @client.on("world")
        def _on_world(data):
            print("[FoundrySocket] Received 'world' event (Foundry world loaded)")

        @client.on("*")
        def _catch_all(event, *args):
            if event not in ("connect", "disconnect", "session", "world", self.EVENT_NAME):
                print(f"[FoundrySocket] Unknown event {event!r}: {str(args)[:300]}")

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
