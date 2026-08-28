"""
A WebDAV share.

WebDAV is what Nextcloud, ownCloud, Box, Fastmail and most NAS boxes speak, and
it is the closest thing to a universal "remote folder" protocol: four verbs the
app already thinks in (PROPFIND to list, GET, PUT, DELETE) over ordinary HTTPS,
authenticated with a username and password. No OAuth application to register,
no token to refresh, nothing to keep running on your side.

Give it the collection URL your provider shows you, e.g.

    https://cloud.example.com/remote.php/dav/files/alice

and a folder to keep the library in. Use an *app password* where your provider
offers one -- Nextcloud and Fastmail both do -- so this file never holds the
password to your whole account.
"""
from __future__ import annotations

import json
import posixpath
from typing import Any, List, Optional
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import requests
from requests.auth import HTTPBasicAuth

from app.storage.base import ENCOUNTERS, StorageBackend

_DAV = "{DAV:}"

# Ask for the least the server can tell us: we only need to know which hrefs
# are collections so directories are not listed as if they were encounters.
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
)


class WebDavStorage(StorageBackend):
    """JSON files in a WebDAV collection."""

    provider_id = "webdav"

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        folder: str = "",
        session: Optional[requests.Session] = None,
    ) -> None:
        if not base_url:
            raise ValueError("a WebDAV URL is required")
        self.base_url = base_url.rstrip("/")
        self.folder = (folder or "").strip("/")
        self.location = f"{self.base_url}/{self.folder}" if self.folder else self.base_url
        self.session = session or requests.Session()
        if username:
            self.session.auth = HTTPBasicAuth(username, password)
        # Collections created this run, so a save does not re-MKCOL every time.
        self._ensured: set = set()

    # ---- urls ----

    def _dir_url(self, collection: str) -> str:
        parts = [self.base_url]
        if self.folder:
            parts.append(quote(self.folder))
        if collection != ENCOUNTERS:
            parts.append(quote(collection))
        return "/".join(parts)

    def _key_url(self, collection: str, key: str) -> str:
        return f"{self._dir_url(collection)}/{quote(key)}"

    # ---- helpers ----

    def _ensure_collection(self, collection: str) -> None:
        """MKCOL the collection and its parents, ignoring "already there".

        Walked from the top down because MKCOL fails with 409 when the parent
        is missing -- creating `.../DnD Tracker/spells` in one call only works
        if `.../DnD Tracker` already exists.
        """
        if collection in self._ensured:
            return
        segments = []
        if self.folder:
            segments.append(quote(self.folder))
        if collection != ENCOUNTERS:
            segments.append(quote(collection))

        url = self.base_url
        for segment in segments:
            url = f"{url}/{segment}"
            r = self.session.request("MKCOL", url, timeout=10)
            # 201 created, 405 already exists, 301/302 some servers redirect.
            if r.status_code not in (201, 301, 302, 405):
                r.raise_for_status()
        self._ensured.add(collection)

    @staticmethod
    def _names_from_multistatus(xml_text: str, dir_path: str) -> List[str]:
        """Filenames directly inside `dir_path`, skipping subcollections."""
        root = ElementTree.fromstring(xml_text)
        names: List[str] = []
        for response in root.findall(f"{_DAV}response"):
            href_el = response.find(f"{_DAV}href")
            if href_el is None or not href_el.text:
                continue
            path = unquote(urlsplit(href_el.text).path).rstrip("/")
            # The collection itself comes back as the first entry.
            if path == dir_path.rstrip("/"):
                continue
            if response.find(f".//{_DAV}resourcetype/{_DAV}collection") is not None:
                continue
            names.append(posixpath.basename(path))
        return names

    # ---- contract ----

    def _list(self, collection: str) -> List[str]:
        url = self._dir_url(collection)
        r = self.session.request(
            "PROPFIND",
            url,
            data=_PROPFIND_BODY.encode("utf-8"),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            timeout=15,
        )
        if r.status_code == 404:
            # Nothing saved here yet; not an error.
            return []
        r.raise_for_status()
        try:
            names = self._names_from_multistatus(r.text, unquote(urlsplit(url).path))
        except ElementTree.ParseError as exc:
            raise RuntimeError(f"Could not read the WebDAV listing: {exc}") from exc
        return sorted(n for n in names if n.endswith(".json") and not n.startswith("."))

    def _read(self, collection: str, key: str) -> Optional[dict]:
        r = self.session.get(self._key_url(collection, key), timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        try:
            return json.loads(r.content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"{collection}/{key} is not valid JSON: {exc}") from exc

    def _write(self, collection: str, key: str, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        url = self._key_url(collection, key)
        headers = {"Content-Type": "application/json"}
        r = self.session.put(url, data=body, headers=headers, timeout=20)
        if r.status_code == 409:
            # 409 is WebDAV for "the parent collection is missing". Make it and
            # try once more, rather than making the user pre-create folders.
            self._ensure_collection(collection)
            r = self.session.put(url, data=body, headers=headers, timeout=20)
        r.raise_for_status()

    def _delete(self, collection: str, key: str) -> None:
        r = self.session.delete(self._key_url(collection, key), timeout=15)
        if r.status_code not in (200, 202, 204, 404):
            r.raise_for_status()
