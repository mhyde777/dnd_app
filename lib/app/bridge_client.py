from __future__ import annotations

import json
import os
import threading
import time
import traceback
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Dict, Optional

import requests


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return default


def _build_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_bridge_poll_seconds() -> float:
    value = _get_env("BRIDGE_POLL_SECONDS", "1")
    try:
        return max(0.25, float(value))
    except ValueError:
        return 1.0


class BridgePoller:
    def __init__(
        self,
        client: "BridgeClient",
        poll_seconds: float,
        on_snapshot: Callable[[Dict[str, Any]], None],
    ) -> None:
        self.client = client
        self.poll_seconds = max(0.25, poll_seconds)
        self.on_snapshot = on_snapshot
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_hash: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("[BridgePoller] start() called; poller thread launched.")

    def stop(self) -> None:
        self._stop_event.set()

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _snapshot_hash(self, snapshot: Dict[str, Any]) -> tuple[str, int]:
        payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        payload_bytes = payload.encode("utf-8")
        digest = sha256(payload_bytes).hexdigest()
        return digest, len(payload_bytes)

    def _is_duplicate(self, digest: str) -> bool:
        if digest == self._last_hash:
            return True
        self._last_hash = digest
        return False

    def _run(self) -> None:
        print("[BridgePoller] _run() entered.")
        while not self._stop_event.is_set():
            try:
                started_at = time.perf_counter()
                snapshot = self.client.fetch_state()
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                if snapshot:
                    digest, payload_len = self._snapshot_hash(snapshot)
                    is_duplicate = self._is_duplicate(digest)
                    print(
                        "[BridgePoller] polled /state ok "
                        f"latency_ms={elapsed_ms:.1f} "
                        f"hash={digest[:8]} "
                        f"duplicate={is_duplicate} "
                        f"bytes={payload_len}"
                    )
                    if not is_duplicate:
                        try:
                            self.on_snapshot(snapshot)
                        except Exception as exc:
                            print(f"[Bridge] Failed to handle snapshot: {exc}")
                else:
                    print(
                        "[BridgePoller] polled /state failed "
                        f"latency_ms={elapsed_ms:.1f} "
                        "hash=-------- duplicate=False bytes=0"
                    )
            except Exception as exc:
                print(f"[BridgePoller] Polling loop crashed: {exc}")
                print(traceback.format_exc())
            self._stop_event.wait(self.poll_seconds)


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

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def fetch_state(self) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            print("[Bridge] BRIDGE_TOKEN is not set; skipping sync.")
            return None
        url = f"{self.base_url}/state"
        try:
            response = requests.get(url, headers=_build_headers(self.token), timeout=self.timeout_s)
        except requests.RequestException as exc:
            print(f"[Bridge] GET /state request failed: {exc}")
            return None
        if response.status_code != 200:
            body_preview = (response.text or "")[:300]
            print(f"[Bridge] GET /state failed: {response.status_code} {body_preview}")
            return None
        try:
            return response.json()
        except ValueError as exc:
            body_preview = (response.text or "")[:300]
            print(f"[Bridge] GET /state JSON decode failed: {exc} body={body_preview}")
            return None

    def send_set_hp(self, token_id: str, hp: int, actor_id: Optional[str] = None) -> bool:
        if not self.enabled:
            print("[BridgeCmd] send_set_hp ok=False reason=missing_token")
            return False

        url = f"{self.base_url}/commands"
        payload: Dict[str, Any] = {
            "source": "app",
            "type": "set_hp",
            "tokenId": token_id,
            "hp": int(hp),
        }
        if actor_id:
            payload["actorId"] = actor_id

        ok = False
        status = None
        try:
            response = requests.post(
                url,
                headers=_build_headers(self.token),
                json=payload,
                timeout=self.timeout_s,
            )
            status = response.status_code
            ok = response.ok
        except requests.RequestException as exc:
            status = str(exc)
            ok = False

        print(
            "[BridgeCmd] send_set_hp "
            f"tokenId={token_id} hp={hp} ok={ok} status={status}"
        )
        return ok
