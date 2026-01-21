import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, "").strip()
    return value if value else (default or "")


@dataclass
class SnapshotStore:
    snapshot: Optional[Dict[str, Any]] = None
    lock: threading.Lock = threading.Lock()

    def get(self) -> Dict[str, Any]:
        with self.lock:
            return self.snapshot or {}

    def set(self, snapshot: Dict[str, Any]) -> None:
        with self.lock:
            self.snapshot = snapshot


@dataclass
class CommandQueue:
    queue: List[Dict[str, Any]] = None
    lock: threading.Lock = threading.Lock()

    def __post_init__(self) -> None:
        if self.queue is None:
            self.queue = []

    def put(self, cmd: Dict[str, Any]) -> None:
        with self.lock:
            self.queue.append(cmd)

    def get_next(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.queue[0] if self.queue else None

    def ack(self, cmd_id: str) -> bool:
        with self.lock:
            for i, c in enumerate(self.queue):
                if c["id"] == cmd_id:
                    self.queue.pop(i)
                    return True
            return False


def create_app() -> Flask:
    app = Flask(__name__)

    ALLOWED_ORIGINS = {
        "https://foundry.masonhyde.com",
        "http://localhost:30000",
    }

    store = SnapshotStore()
    commands = CommandQueue()

    @app.after_request
    def cors(resp):
        origin = request.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-Bridge-Secret"
            )
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    def require_bearer():
        token = _load_env("BRIDGE_TOKEN")
        if not token:
            return jsonify({"error": "BRIDGE_TOKEN not set"}), 503
        if request.headers.get("Authorization") != f"Bearer {token}":
            return jsonify({"error": "unauthorized"}), 401
        return None

    def require_ingest_secret():
        secret = _load_env("BRIDGE_INGEST_SECRET")
        if not secret:
            return None
        if request.headers.get("X-Bridge-Secret") != secret:
            return jsonify({"error": "unauthorized"}), 401
        return None

    @app.get("/health")
    def health():
        auth = require_bearer()
        return auth or jsonify({"status": "ok"})

    @app.get("/version")
    def version():
        auth = require_bearer()
        return auth or jsonify({"version": _load_env("BRIDGE_VERSION", "dev")})

    @app.get("/state")
    def state():
        auth = require_bearer()
        return auth or jsonify(store.get())

    @app.route("/foundry/snapshot", methods=["OPTIONS"])
    def snapshot_options():
        return ("", 204)

    @app.post("/foundry/snapshot")
    def snapshot_post():
        auth = require_ingest_secret()
        if auth:
            return auth
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "missing payload"}), 400
        store.set(payload)
        return jsonify({"status": "ok"})

    @app.route("/commands", methods=["OPTIONS"])
    def commands_options():
        return ("", 204)

    @app.get("/commands")
    def commands_get():
        cmd = commands.get_next()
        return jsonify({"commands": [cmd] if cmd else []})

    @app.post("/commands")
    def commands_post():
        auth = require_bearer()
        if auth:
            return auth
        payload = request.get_json(silent=True) or {}
        if "type" not in payload:
            return jsonify({"error": "missing type"}), 400
        cmd = {
            "id": payload.get("id", str(uuid.uuid4())),
            "type": payload["type"],
            "payload": payload.get("payload", {}),
            "timestamp": _utc_now(),
        }
        commands.put(cmd)
        return jsonify({"status": "ok", "command": cmd})

    @app.route("/commands/<cmd_id>/ack", methods=["OPTIONS"])
    def ack_options(cmd_id):
        return ("", 204)

    @app.post("/commands/<cmd_id>/ack")
    def ack_post(cmd_id):
        if not commands.ack(cmd_id):
            return jsonify({"error": "not_found"}), 404
        return jsonify({"status": "ok"})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=_load_env("BRIDGE_HOST", "0.0.0.0"),
        port=int(_load_env("BRIDGE_PORT", "8787")),
        threaded=True,
    )
