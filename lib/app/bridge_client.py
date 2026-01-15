from __future__ import annotations

import os
import threading
from dataclasses import dataclass
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
        self._last_timestamp: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _is_duplicate(self, snapshot: Dict[str, Any]) -> bool:
        timestamp = snapshot.get("timestamp") if isinstance(snapshot, dict) else None
        if not timestamp:
            return False
        if timestamp == self._last_timestamp:
            return True
        self._last_timestamp = timestamp
        return False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                snapshot = self.client.fetch_state()
            except Exception as exc:
                print(f"[Bridge] Failed to fetch state: {exc}")
                snapshot = None
            if snapshot and not self._is_duplicate(snapshot):
                try:
                    self.on_snapshot(snapshot)
                except Exception as exc:
                    print(f"[Bridge] Failed to handle snapshot: {exc}")
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
        response = requests.get(url, headers=_build_headers(self.token), timeout=self.timeout_s)
        if response.status_code != 200:
            print(f"[Bridge] GET /state failed: {response.status_code} {response.text}")
            return None
        return response.json()
