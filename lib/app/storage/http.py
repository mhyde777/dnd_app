"""
An HTTP service that stores JSON under a key.

This is the backend the app has always called "the API", and the reference
implementation in `storage_service/` still answers it unchanged. The endpoints,
where `<collection>` is one of encounters/statblocks/spells/items:

    GET    {base}/v1/<collection>/items    list keys
    GET    {base}/v1/<collection>/{key}    fetch, or 404
    PUT    {base}/v1/<collection>/{key}    store
    DELETE {base}/v1/<collection>/{key}    remove

The shape tolerance below is deliberate and load-bearing: people have written
their own servers against this client, and a list may come back bare, wrapped
as `{"items": [...]}`, or as a list of objects with a `key`/`name`/`id` field.
Accepting all of them costs one function and means nobody's server breaks.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional

import requests

from app.storage.base import StorageBackend

_LIST_KEYS = ("items", "keys", "data", "results", "list")
_NAME_KEYS = ("key", "name", "filename", "path", "id")


class HttpStorage(StorageBackend):
    """Client for an HTTP JSON storage service."""

    provider_id = "http"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        session: Optional[requests.Session] = None,
    ) -> None:
        if not base_url:
            raise ValueError("a server URL is required")
        self.base_url = base_url.rstrip("/")
        self.location = self.base_url
        self.session = session or requests.Session()
        self.api_key = (api_key or "").strip()
        if self.api_key:
            self.session.headers.update({"X-Api-Key": self.api_key})

    # ---- urls ----

    def _collection_url(self, collection: str) -> str:
        return f"{self.base_url}/v1/{collection}"

    def _key_url(self, collection: str, key: str) -> str:
        return f"{self._collection_url(collection)}/{key}"

    # ---- payload shapes ----

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    @classmethod
    def _as_key_list(cls, payload: Any) -> Optional[List[str]]:
        """Pull a list of keys out of whatever shape the server sent, or None."""
        payload = cls._unwrap(payload)

        if isinstance(payload, dict):
            for candidate in _LIST_KEYS:
                if candidate in payload:
                    found = cls._as_key_list(payload[candidate])
                    if found is not None:
                        return found
            return None

        if not isinstance(payload, list):
            return None

        if all(isinstance(x, str) for x in payload):
            return [str(x) for x in payload]

        keys: List[str] = []
        for obj in payload:
            if not isinstance(obj, dict):
                continue
            for name_key in _NAME_KEYS:
                value = obj.get(name_key)
                if isinstance(value, str):
                    keys.append(value)
                    break
        return keys or None

    # ---- contract ----

    def _list(self, collection: str) -> List[str]:
        # Two spellings, because servers differ on whether the collection URL
        # itself lists or needs an explicit /items.
        candidates: Iterable[str] = (
            f"{self._collection_url(collection)}/items",
            self._collection_url(collection),
        )
        last_err: Any = None
        for url in candidates:
            try:
                r = self.session.get(url, timeout=8)
                r.raise_for_status()
                keys = self._as_key_list(r.json())
                if keys is not None:
                    return keys
                last_err = RuntimeError(f"unrecognised list response from {url}")
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"Could not list {collection}: {last_err}")

    def _read(self, collection: str, key: str) -> Optional[dict]:
        try:
            r = self.session.get(self._key_url(collection, key), timeout=8)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            payload = self._unwrap(r.json())
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, str):
                # Some servers store the JSON as a string.
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    pass
            return {"value": payload}
        except Exception as exc:
            raise RuntimeError(f"Could not read {collection}/{key}: {exc}") from exc

    def _write(self, collection: str, key: str, data: Any) -> None:
        try:
            r = self.session.put(
                self._key_url(collection, key), json={"data": data}, timeout=10
            )
            r.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Could not save {collection}/{key}: {exc}") from exc

    def _delete(self, collection: str, key: str) -> None:
        try:
            r = self.session.delete(self._key_url(collection, key), timeout=8)
            if r.status_code not in (200, 204, 404):
                r.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Could not delete {collection}/{key}: {exc}") from exc
