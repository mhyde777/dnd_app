import json
import os
import threading
import uuid
<<<<<<< HEAD
from dataclasses import dataclass
=======
from dataclasses import dataclass, field
>>>>>>> 1643978 (Working towards getting the bridge working again. Foundry can find the bridge but commands are being posted properly)
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
    lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self) -> Dict[str, Any]:
        with self.lock:
            return self.snapshot or {}

    def set(self, snapshot: Dict[str, Any]) -> None:
        with self.lock:
            self.snapshot = snapshot


@dataclass
class CommandQueue:
<<<<<<< HEAD
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
=======
    """
    In-memory command queue.
    GET /commands returns the oldest outstanding command (peek).
    POST /commands/<id>/ack removes it.
    """
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
            for i, c in enumerate(self.items):
                if c.get("id") == cmd_id:
                    self.items.pop(i)
                    return True
            return False


def _load_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return default or ""
>>>>>>> 1643978 (Working towards getting the bridge working again. Foundry can find the bridge but commands are being posted properly)


def create_app() -> Flask:
    app = Flask(__name__)
<<<<<<< HEAD
=======
    store = SnapshotStore()
    commands = CommandQueue()

    # -----------------------
    # CORS (minimal, explicit)
    # -----------------------
    allowed_origin = _load_env("BRIDGE_ALLOWED_ORIGIN", "https://foundry.masonhyde.com")

    @app.after_request
    def _add_cors_headers(resp):
        origin = request.headers.get("Origin", "")
        if origin and origin == allowed_origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Bridge-Secret"
        return resp
>>>>>>> 1643978 (Working towards getting the bridge working again. Foundry can find the bridge but commands are being posted properly)

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

<<<<<<< HEAD
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
=======
    def _persist_snapshot(snapshot: Dict[str, Any]) -> None:
        path = _load_env("BRIDGE_SNAPSHOT_PATH")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, indent=2, sort_keys=True)
        except Exception as exc:
            print(f"[Bridge] Failed to persist snapshot: {exc}")

    # --------
    # Routes
    # --------
    @app.route("/health", methods=["GET", "OPTIONS"])
    def health() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = _require_bearer()
        if auth is not None:
            return auth
        return jsonify({"status": "ok"})

    @app.route("/state", methods=["GET", "OPTIONS"])
    def state() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = _require_bearer()
        if auth is not None:
            return auth
        return jsonify(store.get())

    @app.route("/version", methods=["GET", "OPTIONS"])
    def version() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = _require_bearer()
        if auth is not None:
            return auth
        return jsonify({"version": _load_env("BRIDGE_VERSION", "dev")})

    @app.route("/foundry/snapshot", methods=["POST", "OPTIONS"])
    def foundry_snapshot() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
        auth = _require_ingest_secret()
        if auth is not None:
>>>>>>> 1643978 (Working towards getting the bridge working again. Foundry can find the bridge but commands are being posted properly)
            return auth
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "missing payload"}), 400
        store.set(payload)
<<<<<<< HEAD
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
=======
        _persist_snapshot(payload)
        world = payload.get("world", "")
        combatants = payload.get("combatants", [])
        print(f"[Bridge] Snapshot received world={world!r} combatants={len(combatants)}")
        return jsonify({"status": "ok"})

    # ----------------
    # Commands (queue)
    # ----------------
    @app.route("/commands", methods=["GET", "POST", "OPTIONS"])
    def commands_route() -> Any:
        if request.method == "OPTIONS":
            return ("", 204)

        if request.method == "GET":
            cmd = commands.get_next()
            return jsonify({"commands": [cmd] if cmd else []})

        # POST: enqueue (require bearer)
        auth = _require_bearer()
        if auth is not None:
            return auth

        raw = request.get_json(silent=True) or {}
        if "type" not in raw:
            return jsonify({"error": "missing type"}), 400

        # Accept BOTH:
        # 1) {"type":"set_hp","payload":{...}}
        # 2) {"type":"set_hp","tokenId":"...","hp":7,"actorId":"..."}  <-- current app behavior
        if isinstance(raw.get("payload"), dict) and raw["payload"]:
            cmd_payload = raw["payload"]
        else:
            reserved = {"id", "type", "timestamp", "source", "payload"}
            cmd_payload = {k: v for k, v in raw.items() if k not in reserved}

        cmd = {
            "id": raw.get("id", str(uuid.uuid4())),
            "type": raw["type"],
            "payload": cmd_payload,
>>>>>>> 1643978 (Working towards getting the bridge working again. Foundry can find the bridge but commands are being posted properly)
            "timestamp": _utc_now(),
        }
        commands.put(cmd)
        return jsonify({"status": "ok", "command": cmd})

<<<<<<< HEAD
    @app.route("/commands/<cmd_id>/ack", methods=["OPTIONS"])
    def ack_options(cmd_id):
        return ("", 204)

    @app.post("/commands/<cmd_id>/ack")
    def ack_post(cmd_id):
=======
    @app.route("/commands/<cmd_id>/ack", methods=["POST", "OPTIONS"])
    def commands_ack(cmd_id: str) -> Any:
        if request.method == "OPTIONS":
            return ("", 204)
>>>>>>> 1643978 (Working towards getting the bridge working again. Foundry can find the bridge but commands are being posted properly)
        if not commands.ack(cmd_id):
            return jsonify({"error": "not_found"}), 404
        return jsonify({"status": "ok"})

    return app


if __name__ == "__main__":
    app = create_app()
<<<<<<< HEAD
    app.run(
        host=_load_env("BRIDGE_HOST", "0.0.0.0"),
        port=int(_load_env("BRIDGE_PORT", "8787")),
        threaded=True,
    )
=======
    app.run(host=host, port=port, threaded=True)

>>>>>>> 1643978 (Working towards getting the bridge working again. Foundry can find the bridge but commands are being posted properly)
