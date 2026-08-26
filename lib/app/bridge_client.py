from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import requests

from app.app_log import get_logger


def _log(message: str) -> None:
    """Bridge chatter goes to the app log, not stdout.

    The packaged build runs console=False, so _log() is discarded -- which
    matters more now that commands are delivered on a worker thread, where a
    failure has no other way to surface.
    """
    level = 30 if ("failed" in message or "error" in message.lower()) else 20
    get_logger().log(level, "%s", message)


def _get_env(name: str, default: str = "") -> str:
    """Bridge config, from settings.json first and the environment second.

    Routed through config so the GUI is authoritative and users never edit a
    dotfile; .env still works for setups that predate the dialog.
    """
    from app.config import bridge_value
    return bridge_value(name, default)


def _build_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_command_payload(
    command_type: str,
    payload: Dict[str, Any],
    command_id: Optional[str] = None,
) -> Dict[str, Any]:
    cmd: Dict[str, Any] = {"source": "app", "type": command_type, "payload": payload}
    if command_id:
        cmd["id"] = command_id
    return cmd


def _build_set_hp_payload(
    token_id: str,
    hp: int,
    actor_id: Optional[str] = None,
    command_id: Optional[str] = None,
) -> Dict[str, Any]:
    cmd: Dict[str, Any] = {"source": "app", "type": "set_hp", "tokenId": token_id, "hp": hp}
    if actor_id:
        cmd["actorId"] = actor_id
    if command_id:
        cmd["id"] = command_id
    return cmd


@dataclass
class BridgeClient:
    base_url: str
    token: str
    timeout_s: float = 3.0

    @classmethod
    def from_env(cls) -> "BridgeClient":
        base_url = _get_env("BRIDGE_URL", "http://127.0.0.1:8787").rstrip("/")
        token = _get_env("BRIDGE_TOKEN")
        timeout_s = float(_get_env("BRIDGE_TIMEOUT", "3"))
        return cls(base_url=base_url, token=token, timeout_s=timeout_s)

    def __post_init__(self) -> None:
        import queue
        import threading

        self._command_queue: "queue.Queue" = queue.Queue()
        self._worker_lock = threading.Lock()
        self._command_worker = None

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def fetch_state(self) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            _log("[Bridge] BRIDGE_TOKEN is not set; skipping sync.")
            return None
        url = f"{self.base_url}/state"
        response = requests.get(url, headers=_build_headers(self.token), timeout=self.timeout_s)
        if response.status_code != 200:
            _log(f"[Bridge] GET /state failed: {response.status_code} {response.text}")
            return None
        return response.json()

    def stream_state(
        self,
        on_snapshot: Callable[[Dict[str, Any]], None],
        stop_event: "threading.Event",
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ) -> None:
        if not self.enabled:
            _log("[Bridge] BRIDGE_TOKEN is not set; skipping stream.")
            return
        import threading
        import time
        import json as jsonlib

        url = f"{self.base_url}/state/stream"
        headers = _build_headers(self.token)
        retry_delay = float(_get_env("BRIDGE_STREAM_RETRY_DELAY", "2"))
        # timeout_s is sized for a single request-response; applying it to a
        # long-lived stream means the read expires every few seconds while the
        # connection is merely idle, so the stream dies and reconnects in a
        # loop -- polling, but worse. Connect keeps the short timeout; the read
        # gets one longer than any sane server keepalive, so a genuinely dead
        # connection is still noticed instead of hanging forever.
        read_timeout = float(_get_env("BRIDGE_STREAM_READ_TIMEOUT", "65"))
        while not stop_event.is_set():
            try:
                with requests.get(
                    url,
                    headers=headers,
                    timeout=(self.timeout_s, read_timeout),
                    stream=True,
                ) as response:
                    if response.status_code != 200:
                        _log(
                            f"[Bridge] GET /state/stream failed: {response.status_code} {response.text}"
                        )
                        if on_disconnect:
                            on_disconnect()
                        time.sleep(retry_delay)
                        continue
                    if on_connect:
                        on_connect()
                    for line in response.iter_lines(decode_unicode=True):
                        if stop_event.is_set():
                            return
                        if not line:
                            continue
                        if line.startswith(":"):
                            continue
                        if line.startswith("data:"):
                            raw = line[len("data:") :].strip()
                            if not raw:
                                continue
                            try:
                                payload = jsonlib.loads(raw)
                            except jsonlib.JSONDecodeError:
                                continue
                            if isinstance(payload, dict):
                                on_snapshot(payload)
            except requests.RequestException as exc:
                _log(f"[Bridge] Stream error: {exc}")
                if on_disconnect:
                    on_disconnect()
                time.sleep(retry_delay)

    def enqueue_set_hp(
        self,
        token_id: str,
        hp: int,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload = {"tokenId": token_id, "hp": int(hp)}
        if actor_id:
            payload["actorId"] = actor_id
        return self._post_command(
            command_type="set_hp",
            payload=payload,
            command_id=command_id,
            log_label="set_hp",
            redact_fields=("tokenId", "actorId"),
        )

    def enqueue_set_temp_hp(
        self,
        token_id: str,
        temp_hp: int,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload = {"tokenId": token_id, "temp": int(temp_hp)}
        if actor_id:
            payload["actorId"] = actor_id
        return self._post_command(
            command_type="set_temp_hp",
            payload=payload,
            command_id=command_id,
            log_label="set_temp_hp",
            redact_fields=("tokenId", "actorId"),
        )

    def enqueue_set_max_hp_bonus(
        self,
        token_id: str,
        max_hp_bonus: int,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        payload = {"tokenId": token_id, "tempmax": int(max_hp_bonus)}
        if actor_id:
            payload["actorId"] = actor_id
        return self._post_command(
            command_type="set_max_hp_bonus",
            payload=payload,
            command_id=command_id,
            log_label="set_max_hp_bonus",
            redact_fields=("tokenId", "actorId"),
        )

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
        return self._post_command(
            command_type="set_initiative",
            payload=payload,
            command_id=command_id,
            log_label="set_initiative",
            redact_fields=("combatantId", "tokenId", "actorId"),
        )

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
        return self._post_command(
            command_type="add_condition",
            payload=payload,
            command_id=command_id,
            log_label="add_condition",
            redact_fields=("tokenId", "actorId", "effectId"),
        )

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
        return self._post_command(
            command_type="remove_condition",
            payload=payload,
            command_id=command_id,
            log_label="remove_condition",
            redact_fields=("tokenId", "actorId", "effectId"),
        )

    def send_next_turn(self, command_id: Optional[str] = None) -> bool:
        return self._post_command(
            command_type="next_turn",
            payload={},
            command_id=command_id,
            log_label="next_turn",
        )

    def send_prev_turn(self, command_id: Optional[str] = None) -> bool:
        return self._post_command(
            command_type="prev_turn",
            payload={},
            command_id=command_id,
            log_label="prev_turn",
        )

    def send_create_journal(
        self,
        name: str,
        content: str,
        command_id: Optional[str] = None,
    ) -> bool:
        """Create or update a Foundry journal entry (used by the shop generator).

        The Foundry module has handled create_journal all along; the app-side
        method was simply missing, so the caller hit AttributeError. Payload
        keys match applyCreateJournal() in foundryvtt-bridge/bridge.js.
        """
        return self._post_command(
            command_type="create_journal",
            payload={"name": name, "content": content},
            command_id=command_id,
            log_label="create_journal",
        )

    def _post_command(
        self,
        command_type: str,
        payload: Dict[str, Any],
        command_id: Optional[str],
        log_label: str,
        redact_fields: tuple[str, ...] = (),
    ) -> bool:
        """Queue a command for delivery and return immediately.

        This used to POST inline. Every caller is on the Qt GUI thread, so a
        turn change waited on a round trip to the bridge before the table could
        repaint -- measured at ~460ms against a remote bridge, which is the
        whole of the delay between pressing Next and seeing anything happen.
        Nothing reads the result: every command here is fire-and-forget.

        A single worker with a FIFO queue, not a thread per command, because
        order matters -- two next_turns must arrive in the order they were
        pressed.
        """
        if not self.enabled:
            _log("[Bridge] BRIDGE_TOKEN is not set; skipping command enqueue.")
            return False

        self._ensure_command_worker()
        self._command_queue.put(
            (command_type, payload, command_id, log_label, redact_fields)
        )
        return True

    # ---- delivery worker ----------------------------------------------------

    def _ensure_command_worker(self) -> None:
        import threading

        with self._worker_lock:
            worker = getattr(self, "_command_worker", None)
            if worker is not None and worker.is_alive():
                return
            self._command_worker = threading.Thread(
                target=self._drain_commands, name="bridge-commands", daemon=True
            )
            self._command_worker.start()

    def _drain_commands(self) -> None:
        while True:
            item = self._command_queue.get()
            try:
                if item is None:            # shutdown sentinel
                    return
                self._post_command_now(*item)
            except Exception as exc:        # never let one bad command kill the worker
                _log(f"[Bridge] command delivery failed: {exc}")
            finally:
                self._command_queue.task_done()

    def flush_commands(self, timeout: float = 2.0) -> None:
        """Give queued commands a moment to go out, on the way to quitting.

        Best effort and time-boxed: a slow bridge must not hold the app open.
        """
        import threading

        finished = threading.Event()

        def waiter():
            self._command_queue.join()
            finished.set()

        threading.Thread(target=waiter, daemon=True).start()
        finished.wait(timeout)

    def _post_command_now(
        self,
        command_type: str,
        payload: Dict[str, Any],
        command_id: Optional[str],
        log_label: str,
        redact_fields: tuple[str, ...] = (),
    ) -> bool:
        if not self.enabled:
            _log("[Bridge] BRIDGE_TOKEN is not set; skipping command enqueue.")
            return False
        url = f"{self.base_url}/commands"
        cmd = _build_command_payload(command_type, payload, command_id=command_id)
        headers = _build_headers(self.token)
        headers["Content-Type"] = "application/json"
        try:
            if command_type == "set_initiative":
                _log(f"[Bridge][DBG] POST {url} type=set_initiative json={payload}")
            response = requests.post(
                url, json=cmd, headers=headers, timeout=self.timeout_s
            )
            if command_type == "set_initiative":
                _log(
                    f"[Bridge][DBG] POST /commands status={response.status_code} body={response.text[:200]}"
                )
        except requests.RequestException as exc:
            _log(f"[Bridge] POST /commands failed: {exc}")
            return False
        if 200 <= response.status_code < 300:
            redacted = " ".join(f"{field}=<redacted>" for field in redact_fields)
            _log(
                f"[Bridge] Enqueued {log_label} command {redacted} status={response.status_code}"
            )
            return True
        _log(
            f"[Bridge] POST /commands failed: {response.status_code} {response.text}"
        )
        return False
