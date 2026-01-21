import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return default or ""


@dataclass
class SnapshotStore:
    snapshot: Optional[Dict[str, Any]] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self) -> Dict[str, Any]:
        with self.lock:
            return self.snapshot or {}

    def set(self, snapshot: Dict[str, Any]) -> None:
        with self.lock:
            self.snapshot = snapshot


@dataclass
class CommandQueue:
    """In-memory command queue."""

    items: List[Dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def put(self, cmd: Dict[str, Any]) -> None:
        with self.lock:
            self.items.append(cmd)

    def get_next(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.items[0] if self.items else None

    def ack(self, cmd_id: str) -> bool:
        with self.lock:
            for i, cmd in enumerate(self.items):
                if cmd.get("id") == cmd_id:
                    self.items.pop(i)
                    return True
            return False


RESERVED_COMMAND_FIELDS = {"id", "type", "timestamp", "source", "payload"}


def _normalize_command(raw: Dict[str, Any]) -> Dict[str, Any]:
    payload = raw.get("payload")
    if not isinstance(payload, dict) or not payload:
        payload = {key: value for key, value in raw.items() if key not in RESERVED_COMMAND_FIELDS}
    command: Dict[str, Any] = {
        "id": raw.get("id", str(uuid.uuid4())),
        "type": raw["type"],
        "payload": payload,
        "timestamp": raw.get("timestamp") or _utc_now(),
    }
    if raw.get("source"):
        command["source"] = raw["source"]
    return command


def create_app() -> Flask:
    app = Flask(__name__)
    store = SnapshotStore()
    commands = CommandQueue()

    allowed_origins = {
        "https://foundry.masonhyde.com",
        "http://localhost:30000",
    }

    @app.after_request
    def cors(resp):
        origin = request.headers.get("Origin")
        if origin in allowed_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-Bridge-Secret"
            )
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    def require_bearer() -> Optional[Tuple[Any, int]]:
        token = _load_env("BRIDGE_TOKEN")
        if not token:
            return jsonify({"error": "BRIDGE_TOKEN not set"}), 503
        if request.headers.get("Authorization") != f"Bearer {token}":
            return jsonify({"error": "unauthorized"}), 401
        return None

    def require_ingest_secret() -> Optional[Tuple[Any, int]]:
        secret = _load_env("BRIDGE_INGEST_SECRET")
        if not secret:
            return None
        if request.headers.get("X-Bridge-Secret") != secret:
            return jsonify({"error": "unauthorized"}), 401
        return None

    def persist_snapshot(snapshot: Dict[str, Any]) -> None:
        path = _load_env("BRIDGE_SNAPSHOT_PATH")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, indent=2, sort_keys=True)
        except Exception as exc:
            print(f"[Bridge] Failed to persist snapshot: {exc}")

    @app.route("/health", methods=["GET", "OPTIONS"])
    def health() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = require_bearer()
        if auth:
            return auth
        return jsonify({"status": "ok"})

    @app.route("/version", methods=["GET", "OPTIONS"])
    def version() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = require_bearer()
        if auth:
            return auth
        return jsonify({"version": _load_env("BRIDGE_VERSION", "dev")})

    @app.route("/state", methods=["GET", "OPTIONS"])
    def state() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = require_bearer()
        if auth:
            return auth
        return jsonify(store.get())

    @app.route("/foundry/snapshot", methods=["POST", "OPTIONS"])
    def foundry_snapshot() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = require_ingest_secret()
        if auth:
            return auth
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "missing payload"}), 400
        store.set(payload)
        persist_snapshot(payload)
        world = payload.get("world", "")
        combatants = payload.get("combatants", [])
        print(f"[Bridge] Snapshot received world={world!r} combatants={len(combatants)}")
        return jsonify({"status": "ok"})

    @app.route("/commands", methods=["GET", "POST", "OPTIONS"])
    def commands_route() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        if request.method == "GET":
            cmd = commands.get_next()
            count = 1 if cmd else 0
            print(f"[Bridge] Commands polled count={count}")
            return jsonify({"commands": [cmd] if cmd else []})

        auth = require_bearer()
        if auth:
            return auth

        raw = request.get_json(silent=True) or {}
        if "type" not in raw:
            return jsonify({"error": "missing type"}), 400

        cmd = _normalize_command(raw)
        commands.put(cmd)
        return jsonify({"status": "ok", "command": cmd})

    @app.route("/commands/<cmd_id>/ack", methods=["POST", "OPTIONS"])
    def commands_ack(cmd_id: str) -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        if not commands.ack(cmd_id):
            print(f"[Bridge] Command ack missing id={cmd_id}")
            return jsonify({"error": "not_found"}), 404
        print(f"[Bridge] Command acked id={cmd_id}")
        return jsonify({"status": "ok"})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=_load_env("BRIDGE_HOST", "0.0.0.0"),
        port=int(_load_env("BRIDGE_PORT", "8787")),
        threaded=True,
    )
