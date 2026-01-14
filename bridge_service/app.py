import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_snapshot() -> Dict[str, Any]:
    return {
        "source": "foundry",
        "world": "",
        "timestamp": _utc_now(),
        "combat": {
            "active": False,
            "id": None,
            "round": 0,
            "turn": 0,
            "activeCombatant": None,
        },
        "combatants": [],
    }


@dataclass
class SnapshotStore:
    snapshot: Optional[Dict[str, Any]] = None
    lock: threading.Lock = threading.Lock()

    def get(self) -> Dict[str, Any]:
        with self.lock:
            if self.snapshot is None:
                return _default_snapshot()
            return self.snapshot

    def set(self, snapshot: Dict[str, Any]) -> None:
        with self.lock:
            self.snapshot = snapshot


def _load_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return default or ""


def create_app() -> Flask:
    app = Flask(__name__)
    store = SnapshotStore()

    def _require_bearer() -> Optional[Any]:
        token = _load_env("BRIDGE_TOKEN")
        if not token:
            return jsonify({"error": "BRIDGE_TOKEN not set"}), 503
        header = request.headers.get("Authorization", "")
        if header != f"Bearer {token}":
            return jsonify({"error": "unauthorized"}), 401
        return None

    def _require_ingest_secret() -> Optional[Any]:
        secret = _load_env("BRIDGE_INGEST_SECRET")
        if not secret:
            return None
        header = request.headers.get("X-Bridge-Secret", "")
        if header != secret:
            return jsonify({"error": "unauthorized"}), 401
        return None

    def _persist_snapshot(snapshot: Dict[str, Any]) -> None:
        path = _load_env("BRIDGE_SNAPSHOT_PATH")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, indent=2, sort_keys=True)
        except Exception as exc:
            print(f"[Bridge] Failed to persist snapshot: {exc}")

    @app.get("/health")
    def health() -> Any:
        auth = _require_bearer()
        if auth is not None:
            return auth
        return jsonify({"status": "ok"})

    @app.get("/state")
    def state() -> Any:
        auth = _require_bearer()
        if auth is not None:
            return auth
        return jsonify(store.get())

    @app.get("/version")
    def version() -> Any:
        auth = _require_bearer()
        if auth is not None:
            return auth
        return jsonify({"version": _load_env("BRIDGE_VERSION", "dev")})

    @app.post("/foundry/snapshot")
    def foundry_snapshot() -> Any:
        auth = _require_ingest_secret()
        if auth is not None:
            return auth
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "missing payload"}), 400
        store.set(payload)
        _persist_snapshot(payload)
        world = payload.get("world", "")
        combatants = payload.get("combatants", [])
        print(
            f"[Bridge] Snapshot received world={world!r} combatants={len(combatants)}"
        )
        return jsonify({"status": "ok"})

    return app


if __name__ == "__main__":
    host = _load_env("BRIDGE_HOST", "127.0.0.1")
    port = int(_load_env("BRIDGE_PORT", "8787"))
    app = create_app()
    app.run(host=host, port=port, threaded=True)
