import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, List
from uuid import uuid4

from flask import Flask, jsonify, request, make_response


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


@dataclass
class CommandQueue:
    commands: List[Dict[str, Any]]
    lock: threading.Lock
    path: str = ""

    @classmethod
    def from_path(cls, path: str) -> "CommandQueue":
        queue = cls(commands=[], lock=threading.Lock(), path=path)
        queue._load()
        return queue

    def _load(self) -> None:
        if not self.path:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                commands = payload.get("commands", [])
            else:
                commands = payload
            if isinstance(commands, list):
                self.commands = [c for c in commands if isinstance(c, dict)]
        except FileNotFoundError:
            return
        except Exception as exc:
            print(f"[BridgeCmd] Failed to load commands: {exc}")

    def _persist(self) -> None:
        if not self.path:
            return
        dir_name = os.path.dirname(self.path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump({"commands": self.commands}, handle, indent=2, sort_keys=True)
        except Exception as exc:
            print(f"[BridgeCmd] Failed to persist commands: {exc}")

    def list(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.commands)

    def enqueue(self, command: Dict[str, Any]) -> None:
        with self.lock:
            self.commands.append(command)
            self._persist()

    def ack(self, command_id: str) -> None:
        with self.lock:
            self.commands = [
                command for command in self.commands if command.get("id") != command_id
            ]
            self._persist()


def _load_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return default or ""


def _parse_allowed_origins() -> Set[str]:
    """
    Comma-separated list of allowed origins for browser requests, e.g.
      BRIDGE_ALLOWED_ORIGINS=https://foundry.masonhyde.com,https://other.example.com
    If unset, defaults to allowing your Foundry domain only (safe default).
    """
    raw = _load_env("BRIDGE_ALLOWED_ORIGINS", "https://foundry.masonhyde.com")
    parts = [p.strip() for p in raw.split(",")]
    return {p for p in parts if p}


def create_app() -> Flask:
    app = Flask(__name__)
    store = SnapshotStore()
    commands_path = _load_env("BRIDGE_COMMANDS_PATH", "/var/lib/dnd-bridge/commands.json")
    command_queue = CommandQueue.from_path(commands_path)
    allowed_origins = _parse_allowed_origins()

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
            reason = "missing" if not header else "mismatched"
            print(
                "[Bridge] ingest secret unauthorized "
                f"path={request.path} reason={reason}"
            )
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

    def _apply_cors(resp):
        """
        Allow Foundry (public origin) to POST to a private/LAN/Tailscale bridge endpoint.
        This also opts into Chrome Private Network Access (PNA).
        """
        origin = request.headers.get("Origin")
        if origin and origin in allowed_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-Bridge-Secret"
            )
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            # Chrome Private Network Access
            resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

    @app.after_request
    def _after_request(resp):
        return _apply_cors(resp)

    # --- Preflight handlers (OPTIONS) ---
    @app.route("/foundry/snapshot", methods=["OPTIONS"])
    def foundry_snapshot_options() -> Any:
        # Empty 204; CORS/PNA headers are added in after_request
        return make_response("", 204)

    @app.route("/health", methods=["OPTIONS"])
    def health_options() -> Any:
        return make_response("", 204)

    @app.route("/state", methods=["OPTIONS"])
    def state_options() -> Any:
        return make_response("", 204)

    @app.route("/version", methods=["OPTIONS"])
    def version_options() -> Any:
        return make_response("", 204)

    # --- API ---
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
        print(f"[Bridge] Snapshot received world={world!r} combatants={len(combatants)}")
        return jsonify({"status": "ok"})

    @app.post("/commands")
    def enqueue_command() -> Any:
        auth = _require_bearer()
        if auth is not None:
            return auth

        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "missing payload"}), 400

        cmd_source = payload.get("source")
        cmd_type = payload.get("type")
        token_id = payload.get("tokenId")
        hp_value = payload.get("hp")

        if cmd_source != "app":
            return jsonify({"error": "invalid source"}), 400
        if cmd_type != "set_hp":
            return jsonify({"error": "invalid type"}), 400
        if not token_id:
            return jsonify({"error": "missing tokenId"}), 400

        try:
            hp_value = int(hp_value)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid hp"}), 400

        command_id = payload.get("id") or str(uuid4())
        actor_id = payload.get("actorId")
        command = {
            "id": command_id,
            "source": cmd_source,
            "type": cmd_type,
            "tokenId": token_id,
            "hp": hp_value,
        }
        if actor_id:
            command["actorId"] = actor_id

        command_queue.enqueue(command)
        print(
            "[BridgeCmd] enqueue "
            f"id={command_id} type={cmd_type} tokenId={token_id} hp={hp_value}"
        )
        return jsonify({"ok": True, "id": command_id})

    @app.get("/commands")
    def list_commands() -> Any:
        auth = _require_ingest_secret()
        if auth is not None:
            return auth
        return jsonify({"commands": command_queue.list()})

    @app.post("/commands/<command_id>/ack")
    def ack_command(command_id: str) -> Any:
        auth = _require_ingest_secret()
        if auth is not None:
            return auth

        payload = request.get_json(silent=True) or {}
        status = payload.get("status")
        if status not in {"ok", "error"}:
            return jsonify({"error": "invalid status"}), 400

        command_queue.ack(command_id)
        print(f"[BridgeCmd] ack id={command_id} status={status}")
        return jsonify({"ok": True})

    return app


if __name__ == "__main__":
    host = _load_env("BRIDGE_HOST", "127.0.0.1")
    port = int(_load_env("BRIDGE_PORT", "8787"))
    app = create_app()
    app.run(host=host, port=port, threaded=True)
