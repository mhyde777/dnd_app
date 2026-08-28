"""
An S3-compatible object store.

Covers Amazon S3 and everything that copies its API: Cloudflare R2, Backblaze
B2, Wasabi, DigitalOcean Spaces, MinIO, Ceph, a Synology NAS. One bucket holds
the whole library as ordinary objects, so it is also the cheapest way to keep a
library several machines share without running a server of your own.

Requests are signed with AWS Signature Version 4, implemented here in about
sixty lines rather than by depending on boto3. boto3 and botocore are ~80MB of
wheel with a vendored copy of urllib3, all of which would land in the
PyInstaller bundle, and the app needs four verbs against one bucket. The
signing algorithm is a stable, published spec; the size is not worth it.

Path-style addressing (`{endpoint}/{bucket}/{key}`) is used throughout because
MinIO, R2 and Ceph all accept it, while virtual-host style needs DNS set up
per bucket.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import requests

from app.storage.base import ENCOUNTERS, StorageBackend

_ALGORITHM = "AWS4-HMAC-SHA256"
_SERVICE = "s3"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str,
                 service: str = _SERVICE) -> bytes:
    """The AWS4 derived signing key. `service` is a parameter so the published
    test vectors (which use "iam") can exercise this chain directly."""
    key = _hmac(f"AWS4{secret}".encode("utf-8"), datestamp)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


def canonical_query(params: Dict[str, str]) -> str:
    """Query string in AWS canonical form.

    Built by hand and appended to the URL rather than handed to requests as
    `params=`: urlencode spells a space `+`, SigV4 requires `%20`, and the
    signature is computed over this string. A prefix like "DnD Tracker" would
    otherwise be signed one way and sent another, and every request 403s.
    """
    return "&".join(
        f"{quote(k, safe='~')}={quote(v, safe='~')}"
        for k, v in sorted(params.items())
    )


def canonical_request(
    method: str,
    uri: str,
    query: str,
    headers: Dict[str, str],
    payload_hash: str,
) -> str:
    """The canonical request, per the SigV4 spec. Pure, so it can be asserted on."""
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in sorted(headers))
    return "\n".join([
        method, uri, query, canonical_headers, signed_headers, payload_hash,
    ])


class S3Storage(StorageBackend):
    """JSON objects in an S3-compatible bucket."""

    provider_id = "s3"

    def __init__(
        self,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        endpoint: str = "",
        prefix: str = "",
        session: Optional[requests.Session] = None,
    ) -> None:
        if not bucket:
            raise ValueError("a bucket name is required")
        if not access_key or not secret_key:
            raise ValueError("an access key and secret key are required")
        self.bucket = bucket.strip("/")
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self.region = (region or "us-east-1").strip()
        self.endpoint = (endpoint.strip().rstrip("/")
                         or f"https://s3.{self.region}.amazonaws.com")
        self.prefix = (prefix or "").strip("/")
        self.session = session or requests.Session()
        self.location = f"{self.endpoint}/{self.bucket}" + (
            f"/{self.prefix}" if self.prefix else ""
        )

    # ---- keys ----

    def _object_key(self, collection: str, key: str) -> str:
        parts = [p for p in (self.prefix, self._folder(collection), key) if p]
        return "/".join(parts)

    @staticmethod
    def _folder(collection: str) -> str:
        # Encounters sit at the top of the prefix, matching the folder layout,
        # so a bucket and a synced folder hold the same shape.
        return "" if collection == ENCOUNTERS else collection

    def _collection_prefix(self, collection: str) -> str:
        parts = [p for p in (self.prefix, self._folder(collection)) if p]
        return "/".join(parts) + "/" if parts else ""

    # ---- signing ----

    def _signed_request(
        self,
        method: str,
        canonical_uri: str,
        params: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        host = urlsplit(self.endpoint).netloc
        payload_hash = hashlib.sha256(body).hexdigest() if body else _EMPTY_SHA256

        query = canonical_query(params or {})

        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        headers.update({k.lower(): v for k, v in (extra_headers or {}).items()})
        signed_headers = ";".join(sorted(headers))

        creq = canonical_request(
            method, canonical_uri, query, headers, payload_hash
        )
        scope = f"{datestamp}/{self.region}/{_SERVICE}/aws4_request"
        string_to_sign = "\n".join([
            _ALGORITHM,
            amz_date,
            scope,
            hashlib.sha256(creq.encode("utf-8")).hexdigest(),
        ])
        signature = hmac.new(
            _signing_key(self.secret_key, datestamp, self.region),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers["Authorization"] = (
            f"{_ALGORITHM} Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        url = f"{self.endpoint}{canonical_uri}"
        if query:
            url = f"{url}?{query}"
        return self.session.request(
            method, url, data=body or None, headers=headers, timeout=20,
        )

    @staticmethod
    def _raise_for_s3(response: requests.Response, what: str) -> None:
        if response.ok:
            return
        # S3 error bodies are XML with a human-readable <Message>; surfacing it
        # turns "403 Forbidden" into "The request signature we calculated...".
        detail = ""
        try:
            root = ElementTree.fromstring(response.text)
            message = root.findtext("Message") or root.findtext(f"{_S3_NS}Message")
            code = root.findtext("Code") or root.findtext(f"{_S3_NS}Code")
            detail = " ".join(p for p in (code, message) if p)
        except (ElementTree.ParseError, ValueError):
            detail = response.text[:200]
        raise RuntimeError(
            f"{what} failed: {response.status_code} {detail}".strip()
        )

    # ---- contract ----

    def _list(self, collection: str) -> List[str]:
        prefix = self._collection_prefix(collection)
        keys: List[str] = []
        token: Optional[str] = None
        while True:
            params = {"list-type": "2", "prefix": prefix, "delimiter": "/"}
            if token:
                params["continuation-token"] = token
            r = self._signed_request("GET", f"/{self.bucket}", params=params)
            self._raise_for_s3(r, f"Listing {collection}")
            root = ElementTree.fromstring(r.text)
            for contents in root.findall(f"{_S3_NS}Contents"):
                full = contents.findtext(f"{_S3_NS}Key") or ""
                name = full[len(prefix):]
                # The delimiter keeps subfolders out as CommonPrefixes, but a
                # zero-byte "folder marker" object still comes back here.
                if name and "/" not in name and name.endswith(".json"):
                    keys.append(name)
            if (root.findtext(f"{_S3_NS}IsTruncated") or "").lower() != "true":
                break
            token = root.findtext(f"{_S3_NS}NextContinuationToken")
            if not token:
                break
        return sorted(keys)

    def _read(self, collection: str, key: str) -> Optional[dict]:
        path = f"/{self.bucket}/{quote(self._object_key(collection, key), safe='/~')}"
        r = self._signed_request("GET", path)
        if r.status_code == 404:
            return None
        self._raise_for_s3(r, f"Reading {collection}/{key}")
        try:
            return json.loads(r.content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"{collection}/{key} is not valid JSON: {exc}") from exc

    def _write(self, collection: str, key: str, data: Any) -> None:
        path = f"/{self.bucket}/{quote(self._object_key(collection, key), safe='/~')}"
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        r = self._signed_request(
            "PUT", path, body=body,
            extra_headers={"content-type": "application/json"},
        )
        self._raise_for_s3(r, f"Saving {collection}/{key}")

    def _delete(self, collection: str, key: str) -> None:
        path = f"/{self.bucket}/{quote(self._object_key(collection, key), safe='/~')}"
        r = self._signed_request("DELETE", path)
        if r.status_code == 404:
            return
        self._raise_for_s3(r, f"Deleting {collection}/{key}")
