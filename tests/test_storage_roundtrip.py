"""
Every network backend against a real server over a real socket.

The WebDAV XML and the S3 SigV4 signing in this app are hand-written, and unit
tests on their pure helpers cannot catch the things that actually break: a URL
assembled one way and signed another, a MKCOL that never fires, a listing whose
hrefs are read relative to the wrong base. So each backend here does a full
round trip -- write, list, read, delete, across all four collections -- against
a server started for the test.

The S3 server recomputes the signature *independently*, from the request line
as it arrived, and rejects a mismatch. That is what makes it a real check on
the signing rather than a restatement of it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import socket
import threading
from urllib.parse import quote, unquote, urlsplit

import pytest

pytest.importorskip("flask")
from flask import Flask, Response, request  # noqa: E402

from app.storage import S3Storage, WebDavStorage  # noqa: E402

DAV_USER, DAV_PASS = "alice", "hunter2"
AK, SK, REGION, BUCKET = "AKIAEXAMPLE", "secret-key-value", "us-east-1", "mybucket"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_app(root: str) -> Flask:
    app = Flask(__name__)
    dav_root = os.path.join(root, "dav", "alice")
    s3_root = os.path.join(root, "s3", BUCKET)
    os.makedirs(dav_root, exist_ok=True)
    os.makedirs(s3_root, exist_ok=True)

    # ---- WebDAV ----

    @app.route("/dav/alice/", defaults={"p": ""},
               methods=["PROPFIND", "GET", "PUT", "DELETE", "MKCOL"])
    @app.route("/dav/alice/<path:p>",
               methods=["PROPFIND", "GET", "PUT", "DELETE", "MKCOL"])
    def dav(p):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return Response("no auth", 401)
        user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
        if (user, pw) != (DAV_USER, DAV_PASS):
            return Response("bad auth", 401)

        full = os.path.join(dav_root, unquote(p).strip("/"))
        if request.method == "PROPFIND":
            if not os.path.isdir(full):
                return Response("not found", 404)
            stem = quote(p.strip("/"))
            base = "/dav/alice/" + (stem + "/" if stem else "")
            out = ['<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">',
                   f'<d:response><d:href>{base}</d:href><d:propstat><d:prop>'
                   f'<d:resourcetype><d:collection/></d:resourcetype>'
                   f'</d:prop></d:propstat></d:response>']
            for name in sorted(os.listdir(full)):
                is_dir = os.path.isdir(os.path.join(full, name))
                rtype = "<d:collection/>" if is_dir else ""
                href = base + quote(name) + ("/" if is_dir else "")
                out.append(f'<d:response><d:href>{href}</d:href><d:propstat>'
                           f'<d:prop><d:resourcetype>{rtype}</d:resourcetype>'
                           f'</d:prop></d:propstat></d:response>')
            out.append("</d:multistatus>")
            return Response("".join(out), 207, mimetype="application/xml")

        if request.method == "MKCOL":
            if os.path.isdir(full):
                return Response("exists", 405)
            if not os.path.isdir(os.path.dirname(full)):
                return Response("no parent", 409)
            os.makedirs(full)
            return Response("", 201)

        if request.method == "GET":
            if not os.path.isfile(full):
                return Response("not found", 404)
            return Response(open(full, "rb").read(), 200)

        if request.method == "PUT":
            # The real WebDAV answer when the collection is missing. The
            # client is expected to MKCOL and retry.
            if not os.path.isdir(os.path.dirname(full)):
                return Response("no parent collection", 409)
            open(full, "wb").write(request.get_data())
            return Response("", 201)

        if os.path.isfile(full):
            os.remove(full)
            return Response("", 204)
        return Response("not found", 404)

    # ---- S3 ----

    def signature_problem():
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("AWS4-HMAC-SHA256 "):
            return "missing authorization"
        bits = dict(kv.strip().split("=", 1) for kv in auth[17:].split(","))
        akid, datestamp, region, service, _ = bits["Credential"].split("/")
        if akid != AK:
            return "unknown access key"

        payload_hash = request.headers["x-amz-content-sha256"]
        if hashlib.sha256(request.get_data()).hexdigest() != payload_hash:
            return "payload hash mismatch"

        # From the request line as received -- not from anything the client
        # asserts about what it signed.
        raw = request.environ.get("RAW_URI") or request.environ["REQUEST_URI"]
        split = urlsplit(raw)
        names = bits["SignedHeaders"].split(";")
        canonical_headers = "".join(
            f"{n}:{request.headers[n].strip()}\n" for n in names)
        creq = "\n".join([request.method, split.path, split.query,
                          canonical_headers, bits["SignedHeaders"], payload_hash])
        scope = f"{datestamp}/{region}/{service}/aws4_request"
        sts = "\n".join(["AWS4-HMAC-SHA256", request.headers["x-amz-date"],
                         scope, hashlib.sha256(creq.encode()).hexdigest()])
        key = hmac.new(f"AWS4{SK}".encode(), datestamp.encode(),
                       hashlib.sha256).digest()
        for part in (region, service, "aws4_request"):
            key = hmac.new(key, part.encode(), hashlib.sha256).digest()
        if hmac.new(key, sts.encode(), hashlib.sha256).hexdigest() != bits["Signature"]:
            return "signature mismatch"
        return None

    def s3_error(message, code=403):
        return Response(
            f"<Error><Code>SignatureDoesNotMatch</Code>"
            f"<Message>{message}</Message></Error>",
            code, mimetype="application/xml")

    @app.route(f"/{BUCKET}", methods=["GET"])
    def s3_list():
        problem = signature_problem()
        if problem:
            return s3_error(problem)
        prefix = request.args.get("prefix", "")
        delimiter = request.args.get("delimiter", "")
        keys = []
        for dirpath, _dirs, files in os.walk(s3_root):
            for name in files:
                rel = os.path.relpath(os.path.join(dirpath, name), s3_root)
                rel = rel.replace(os.sep, "/")
                if rel.startswith(prefix) and not (
                    delimiter and delimiter in rel[len(prefix):]
                ):
                    keys.append(rel)
        body = ['<?xml version="1.0"?><ListBucketResult '
                'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">']
        body += [f"<Contents><Key>{k}</Key></Contents>" for k in sorted(keys)]
        body.append("<IsTruncated>false</IsTruncated></ListBucketResult>")
        return Response("".join(body), 200, mimetype="application/xml")

    @app.route(f"/{BUCKET}/<path:key>", methods=["GET", "PUT", "DELETE"])
    def s3_object(key):
        problem = signature_problem()
        if problem:
            return s3_error(problem)
        full = os.path.join(s3_root, key)
        if request.method == "PUT":
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "wb").write(request.get_data())
            return Response("", 200)
        if request.method == "GET":
            if not os.path.isfile(full):
                return Response("<Error><Code>NoSuchKey</Code></Error>", 404)
            return Response(open(full, "rb").read(), 200)
        if os.path.isfile(full):
            os.remove(full)
        return Response("", 204)

    return app


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("wire"))
    port = _free_port()
    from werkzeug.serving import make_server

    httpd = make_server("127.0.0.1", port, _build_app(root), threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    thread.join(timeout=5)


def _exercise(store, encounter_key="goblin caves.json"):
    """Write, list, read and delete across all four collections.

    The default key has a space in it, because that is exactly where URL
    encoding and request signing disagree if either is wrong. The app itself
    normalises spaces to underscores before saving, so the reference server --
    which rejects anything outside [A-Za-z0-9._-] to keep a key from becoming
    a path traversal -- is exercised with a key it would really see.
    """
    assert store.list() == []

    store.put_json(encounter_key, {"round": 3})
    store.save_statblock("goblin.json", {"name": "Goblin"})
    store.save_spell("fireball.json", {"level": 3})
    store.save_item("rope.json", {"cost": "1 gp"})

    assert store.list() == [encounter_key]
    assert store.list_statblock_keys() == ["goblin.json"]
    assert store.list_spell_keys() == ["fireball.json"]
    assert store.list_item_keys() == ["rope.json"]

    assert store.get(encounter_key) == {"round": 3}
    assert store.get_spell("fireball.json") == {"level": 3}
    assert store.get_statblock("goblin.json") == {"name": "Goblin"}
    assert store.get_item("rope.json") == {"cost": "1 gp"}

    # Absent is None, and only absent.
    assert store.get("no_such_encounter.json") is None
    assert store.get_spell("no_such_spell.json") is None

    store.delete_spell("fireball.json")
    assert store.list_spell_keys() == []
    store.delete(encounter_key)
    assert store.list() == []


def test_webdav_round_trip(server):
    # The folder does not exist yet: the client must create it on first write.
    store = WebDavStorage(f"{server}/dav/alice", DAV_USER, DAV_PASS,
                          folder="DnD Tracker")
    _exercise(store)


def test_webdav_listing_an_absent_folder_is_empty_not_an_error(server):
    store = WebDavStorage(f"{server}/dav/alice", DAV_USER, DAV_PASS,
                          folder="Never Created")
    assert store.list() == []


def test_webdav_rejects_wrong_credentials(server):
    store = WebDavStorage(f"{server}/dav/alice", DAV_USER, "wrong")
    with pytest.raises(Exception):
        store.check()


def test_s3_round_trip(server):
    # A space in the prefix too: urlencode would spell it "+" and the server
    # would reject every signature.
    store = S3Storage(BUCKET, AK, SK, region=REGION, endpoint=server,
                      prefix="DnD Tracker")
    _exercise(store)


def test_s3_round_trip_without_a_prefix(server):
    store = S3Storage(BUCKET, AK, SK, region=REGION, endpoint=server)
    _exercise(store)


def test_s3_rejects_a_bad_secret_key(server):
    store = S3Storage(BUCKET, AK, "wrong-secret", region=REGION, endpoint=server)
    with pytest.raises(RuntimeError, match="403"):
        store.check()


def test_s3_surfaces_the_servers_error_message(server):
    """A 403 alone is unactionable; S3 puts the reason in the XML body."""
    store = S3Storage(BUCKET, "AKIAWRONG", SK, region=REGION, endpoint=server)
    with pytest.raises(RuntimeError, match="unknown access key"):
        store.check()


# --------------------------------------------------------------------------
# HttpStorage against the reference server that ships in this repository
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def http_server(tmp_path_factory):
    """The real storage_service, not a mock.

    This pair is the contract the repo publishes: if the shipped client and the
    shipped server ever stop agreeing, that is a broken release, and nothing
    else in the suite would notice.
    """
    from storage_service.app import create_app

    root = str(tmp_path_factory.mktemp("http"))
    port = _free_port()
    from werkzeug.serving import make_server

    httpd = make_server("127.0.0.1", port, create_app(root, "testkey"),
                        threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    thread.join(timeout=5)


def test_http_round_trip_against_the_reference_server(http_server):
    from app.storage import HttpStorage

    _exercise(HttpStorage(http_server, "testkey"), encounter_key="goblin_caves.json")


def test_http_rejects_a_wrong_api_key(http_server):
    from app.storage import HttpStorage

    with pytest.raises(RuntimeError):
        HttpStorage(http_server, "wrong-key").check()
