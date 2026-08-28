# storage_service/app.py
"""
A reference storage server for the D&D Combat Tracker.

The "HTTP server" storage provider points the app at an HTTP service that keeps
its encounters, statblocks, spells and items. This is a small, file-backed
implementation of exactly the endpoints `lib/app/storage/http.py` calls --
enough to run for real, and short enough to read in one sitting if you would
rather write your own.

You do not need this to use the app. "This computer" keeps everything in a
folder and is the default, and there are Dropbox, Google Drive, WebDAV and S3
providers besides. This is worth running when you want several machines to
share one library with no sync client and nothing rented.

    pip install flask
    python -m storage_service.app --data ~/dnd-data --key secret --port 8000

Everything is stored as plain JSON files under --data, one per key, so the data
outlives this server: point the "This computer" provider at the same directory
and the app reads the same encounters.

Deliberately not included: users, TLS, rate limiting. Run it on a private
network or behind something that provides those -- the API key is a guard
against accidents, not an authentication system.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Optional

try:
    from flask import Flask, jsonify, request
except ImportError:  # pragma: no cover - the error message is the feature
    raise SystemExit(
        "Flask is not installed. Install it with:  pip install flask"
    )

# The four collections the app asks for, and the directory each lives in.
COLLECTIONS = {
    "encounters": ".",          # encounters sit at the top, as in local mode
    "statblocks": "statblocks",
    "spells": "spells",
    "items": "items",
}

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe(key: str) -> str:
    """Reject anything that isn't a plain filename.

    The key becomes a path, so a `..` or a slash here is a write anywhere on
    the disk this process can reach.
    """
    if not key or not _SAFE_KEY.match(key) or key in (".", ".."):
        raise ValueError(f"unsafe key: {key!r}")
    return key


def create_app(data_dir: str, api_key: str = "") -> Flask:
    app = Flask(__name__)
    data_dir = os.path.abspath(os.path.expanduser(data_dir))
    for sub in COLLECTIONS.values():
        os.makedirs(os.path.join(data_dir, sub), exist_ok=True)

    def collection_dir(collection: str) -> str:
        return os.path.join(data_dir, COLLECTIONS[collection])

    def path_for(collection: str, key: str) -> str:
        return os.path.join(collection_dir(collection), _safe(key))

    @app.before_request
    def check_key():
        if request.method == "OPTIONS" or not api_key:
            return None
        if request.headers.get("X-Api-Key") != api_key:
            return jsonify({"error": "bad or missing X-Api-Key"}), 401
        return None

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "data_dir": data_dir})

    @app.get("/v1/<collection>/items")
    def list_items(collection: str):
        if collection not in COLLECTIONS:
            return jsonify({"error": "unknown collection"}), 404
        directory = collection_dir(collection)
        try:
            names = sorted(
                name for name in os.listdir(directory)
                if name.endswith(".json") and os.path.isfile(os.path.join(directory, name))
            )
        except OSError:
            names = []
        # The client accepts several shapes; a bare list is the simplest.
        return jsonify(names)

    @app.get("/v1/<collection>/<key>")
    def get_item(collection: str, key: str):
        if collection not in COLLECTIONS:
            return jsonify({"error": "unknown collection"}), 404
        try:
            path = path_for(collection, key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not os.path.isfile(path):
            return jsonify({"error": "not found"}), 404
        with open(path, "r", encoding="utf-8") as handle:
            return jsonify(json.load(handle))

    @app.put("/v1/<collection>/<key>")
    @app.post("/v1/<collection>/<key>")
    def put_item(collection: str, key: str):
        if collection not in COLLECTIONS:
            return jsonify({"error": "unknown collection"}), 404
        try:
            path = path_for(collection, key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        payload: Optional[Any] = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "expected a JSON body"}), 400
        # The client wraps some payloads as {"data": ...}; store what it meant.
        if isinstance(payload, dict) and set(payload) == {"data"}:
            payload = payload["data"]

        # Write and rename, so a failed write can't leave a half-file that
        # parses as a corrupt encounter.
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        return jsonify({"ok": True, "key": key})

    @app.delete("/v1/<collection>/<key>")
    def delete_item(collection: str, key: str):
        if collection not in COLLECTIONS:
            return jsonify({"error": "unknown collection"}), 404
        try:
            path = path_for(collection, key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if os.path.isfile(path):
            os.remove(path)
        return jsonify({"ok": True})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--data", default="~/dnd-tracker-data",
                        help="directory to keep the JSON files in")
    parser.add_argument("--key", default=os.getenv("STORAGE_API_KEY", ""),
                        help="require this X-Api-Key header (empty = no key)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 for this machine only; 0.0.0.0 to share")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    app = create_app(args.data, args.key)
    where = os.path.abspath(os.path.expanduser(args.data))
    print(f"Serving {where}")
    print(f"  URL for the app:  http://{args.host}:{args.port}")
    print(f"  API key:          {'set' if args.key else 'none (anyone who can reach it can read it)'}")
    if args.host == "0.0.0.0" and not args.key:
        print("  WARNING: reachable from the network with no key.")
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
