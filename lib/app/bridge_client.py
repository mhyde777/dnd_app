from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return default


def _build_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_set_hp_payload(
    token_id: str,
    hp: int,
    actor_id: Optional[str] = None,
    command_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": "app",
        "type": "set_hp",
        "tokenId": token_id,
        "hp": int(hp),
    }
    if actor_id:
        payload["actorId"] = actor_id
    if command_id:
        payload["id"] = command_id
    return payload


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

    def enqueue_set_hp(
        self,
        token_id: str,
        hp: int,
        actor_id: Optional[str] = None,
        command_id: Optional[str] = None,
    ) -> bool:
        if not self.enabled:
            print("[Bridge] BRIDGE_TOKEN is not set; skipping command enqueue.")
            return False
        url = f"{self.base_url}/commands"
        payload = _build_set_hp_payload(
            token_id=token_id,
            hp=hp,
            actor_id=actor_id,
            command_id=command_id,
        )
        headers = _build_headers(self.token)
        headers["Content-Type"] = "application/json"
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=self.timeout_s
            )
        except requests.RequestException as exc:
            print(f"[Bridge] POST /commands failed: {exc}")
            return False
        if 200 <= response.status_code < 300:
            print(
                "[Bridge] Enqueued set_hp command"
                f" tokenId=<redacted> actorId={'<redacted>' if actor_id else 'none'}"
                f" status={response.status_code}"
            )
            return True
        print(
            f"[Bridge] POST /commands failed: {response.status_code} {response.text}"
        )
        return False
