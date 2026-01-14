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
