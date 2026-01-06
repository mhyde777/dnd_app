# app/storage_api.py
from __future__ import annotations
import json
from typing import Optional, Any, Dict, Iterable, List
import os

import requests
from requests import Response

from app.creature import CustomEncoder


class StorageAPI:
    """
    Minimal, robust client for your Storage service.

    Expected endpoints (tolerant to minor variants):
      - GET  {base}/v1/encounters/items      -> list of keys or {"items":[...]} or {"data":[...]}
      - GET  {base}/v1/encounters/{key}      -> JSON (raw or {"data": ...})
      - PUT  {base}/v1/encounters/{key}      -> accepts JSON (raw or {"data": ...})
      - DEL  {base}/v1/encounters/{key}
    """

    def __init__(self, base_url: str, session: Optional[requests.Session] = None):
        if not base_url:
            raise ValueError("StorageAPI base_url is required")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.api_key = os.getenv("STORAGE_API_KEY", "").strip()

        # ✅ attach API key for every request made by this Session
        if self.api_key:
            self.session.headers.update({"X-Api-Key": self.api_key})

    # ----- URL helpers -----

    def _encounters_url(self) -> str:
        return f"{self.base_url}/v1/encounters"

    def _items_url(self) -> str:
        return f"{self._encounters_url()}/items"

    def _item_url(self, key: str) -> str:
        return f"{self._encounters_url()}/{key}"

    def _headers(self) -> dict:
        if getattr(self, "api_key", ""):
            return {"X-Api-Key": self.api_key}
        return {}

    # ----- Response helpers -----

    @staticmethod
    def _unwrap_data(maybe_wrapped: Any) -> Any:
        """
        Accept either {"data": ...} or raw payload. Return the inner object.
        """
        if isinstance(maybe_wrapped, dict) and "data" in maybe_wrapped:
            return maybe_wrapped["data"]
        return maybe_wrapped

    @staticmethod
    def _wrap_for_put(data: Any) -> Any:
        """
        Server may expect either {"data": ...} or raw payload. This client
        sends raw JSON by default, but you can switch to {"data": data}
        by returning {"data": data} here if your server requires it.
        """
        return {"data": data}  # change to {"data": data} if your server expects wrapper

    # ----- Core ops -----
    def list(self) -> List[str]:
        """
        Return a list of item keys (e.g., ["Goblin_Caves.json", "players.json", ...]).
        Tries multiple endpoints and normalizes a variety of response shapes.
        """
        import requests
        from requests import HTTPError

        # Candidate endpoints your server might expose
        candidates = [
            self._items_url(),         # .../v1/encounters/items   (your original guess)
            self._encounters_url(),    # .../v1/encounters         (often used for listing)
        ]

        last_err = None
        for url in candidates:
            try:
                r = self.session.get(url, timeout=8)
                r.raise_for_status()
                payload = r.json()
                payload = self._unwrap_data(payload)

                # ---- normalize shapes ----
                # 1) Direct list of strings
                if isinstance(payload, list) and all(isinstance(x, str) for x in payload):
                    return [str(x) for x in payload]

                # 2) Dict with items/keys
                if isinstance(payload, dict):
                    # common keys
                    for k in ("items", "keys", "data", "results", "list"):
                        if k in payload:
                            inner = payload[k]
                            # inner might be list[str] or list[dict]
                            if isinstance(inner, list):
                                # list of strings
                                if all(isinstance(x, str) for x in inner):
                                    return [str(x) for x in inner]
                                # list of dicts -> pull common name fields
                                if all(isinstance(x, dict) for x in inner):
                                    out: List[str] = []
                                    for obj in inner:
                                        for name_key in ("key", "name", "filename", "path", "id"):
                                            if name_key in obj and isinstance(obj[name_key], str):
                                                out.append(obj[name_key])
                                                break
                                    if out:
                                        return out

                    # Sometimes the listing is nested one more level deep
                    # e.g., {"data": {"items": [...]}} handled above via loop

                # 3) List of dicts at top level
                if isinstance(payload, list) and all(isinstance(x, dict) for x in payload):
                    out: List[str] = []
                    for obj in payload:
                        for name_key in ("key", "name", "filename", "path", "id"):
                            if name_key in obj and isinstance(obj[name_key], str):
                                out.append(obj[name_key])
                                break
                    if out:
                        return out

                # If we reach here, shape wasn't recognized; fall through to next candidate
                last_err = RuntimeError(f"Unrecognized list payload shape from {url}: {str(payload)[:200]}")

            except HTTPError as e:
                last_err = e
            except Exception as e:
                last_err = e

        # None of the candidates worked
        raise RuntimeError(f"StorageAPI.list() failed: {last_err}")

    def get(self, key: str) -> Optional[dict]:
        """
        GET the JSON object for a given key. Returns dict or None if 404.
        """
        try:
            r: Response = self.session.get(self._item_url(key), timeout=8)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            payload = r.json()
            payload = self._unwrap_data(payload)
            if isinstance(payload, dict):
                return payload
            # Some servers might store JSON as a string; try to parse.
            if isinstance(payload, str):
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    pass
            # Fallback: wrap into dict
            return {"value": payload}
        except Exception as e:
            raise RuntimeError(f"StorageAPI.get({key}) failed: {e}") from e

    def put(self, key: str, data: Any) -> None:
        """
        PUT arbitrary JSON under a key.
        """
        try:
            body = self._wrap_for_put(data)
            r: Response = self.session.put(self._item_url(key), json=body, timeout=10)
            r.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"StorageAPI.put({key}) failed: {e}") from e

    def delete(self, key: str) -> None:
        """
        DELETE a key.
        """
        try:
            r: Response = self.session.delete(self._item_url(key), timeout=8)
            if r.status_code not in (200, 204, 404):
                r.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"StorageAPI.delete({key}) failed: {e}") from e

    # ----- Helpers tailored to your app’s JSON encoding -----

    def put_json(self, key: str, obj: dict) -> None:
        """PUT using your CustomEncoder to preserve dataclasses, etc."""
        text = json.dumps(obj, cls=CustomEncoder, ensure_ascii=False)
        payload = json.loads(text)
        self.put(key, payload)

    def get_json(self, key: str) -> Optional[dict]:
        """GET and ensure dict result (or None)."""
        return self.get(key)
