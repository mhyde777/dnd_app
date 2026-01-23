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


def _build_command_payload(
    command_type: str,
    payload: Dict[str, Any],
    command_id: Optional[str] = None,
) -> Dict[str, Any]:
    cmd: Dict[str, Any] = {"source": "app", "type": command_type, "payload": payload}
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

    def _post_command(
        self,
        command_type: str,
        payload: Dict[str, Any],
        command_id: Optional[str],
        log_label: str,
        redact_fields: tuple[str, ...] = (),
    ) -> bool:
        if not self.enabled:
            print("[Bridge] BRIDGE_TOKEN is not set; skipping command enqueue.")
            return False
        url = f"{self.base_url}/commands"
        cmd = _build_command_payload(command_type, payload, command_id=command_id)
        headers = _build_headers(self.token)
        headers["Content-Type"] = "application/json"
        try:
            if command_type == "set_initiative":
                print(f"[Bridge][DBG] POST {url} type=set_initiative json={payload}")
            response = requests.post(
                url, json=cmd, headers=headers, timeout=self.timeout_s
            )
            if command_type == "set_initiative":
                print(
                    f"[Bridge][DBG] POST /commands status={response.status_code} body={response.text[:200]}"
                )
        except requests.RequestException as exc:
            print(f"[Bridge] POST /commands failed: {exc}")
            return False
        if 200 <= response.status_code < 300:
            redacted = " ".join(f"{field}=<redacted>" for field in redact_fields)
            print(
                f"[Bridge] Enqueued {log_label} command {redacted} status={response.status_code}"
            )
            return True
        print(
            f"[Bridge] POST /commands failed: {response.status_code} {response.text}"
        )
        return False
