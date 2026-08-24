import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app import update_check  # noqa: E402


@pytest.mark.parametrize("candidate,current,expected", [
    ("0.2.0", "0.1.0", True),
    ("v0.1.1", "0.1.0", True),      # tags usually carry a leading v
    ("0.10.0", "0.9.0", True),      # numeric, not lexical
    ("1.0.0", "0.9.9", True),
    ("0.1.0", "0.1.0", False),
    ("0.0.9", "0.1.0", False),
    ("0.2", "0.2.0", False),        # padded, so these are equal
    ("0.2.0-rc1", "0.2.0", False),  # a pre-release is not an upgrade
    ("0.2.0", "0.2.0-rc1", True),   # ...but leaving one behind is
    ("garbage", "0.1.0", False),
    ("", "0.1.0", False),
])
def test_is_newer(candidate, current, expected):
    assert update_check.is_newer(candidate, current) is expected


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, result):
    def fake(request, timeout=None):
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)
    monkeypatch.setattr(update_check.urllib.request, "urlopen", fake)


def test_fetch_reads_the_tag(monkeypatch):
    _patch_urlopen(monkeypatch, {"tag_name": "v1.2.3"})
    assert update_check.fetch_latest_version() == "v1.2.3"


def test_fetch_falls_back_to_name(monkeypatch):
    _patch_urlopen(monkeypatch, {"name": "1.2.3"})
    assert update_check.fetch_latest_version() == "1.2.3"


def test_network_failure_is_silent(monkeypatch):
    # Playing offline must not surface an update error.
    _patch_urlopen(monkeypatch, OSError("no route to host"))
    assert update_check.fetch_latest_version() is None


def test_malformed_response_is_silent(monkeypatch):
    class Garbage(_FakeResponse):
        def read(self):
            return b"<html>not json</html>"
    monkeypatch.setattr(
        update_check.urllib.request, "urlopen",
        lambda request, timeout=None: Garbage({}),
    )
    assert update_check.fetch_latest_version() is None


def test_background_check_notifies_only_when_newer(monkeypatch):
    monkeypatch.setattr(update_check, "fetch_latest_version", lambda url=None: "9.9.9")
    seen = []
    update_check.check_in_background(seen.append).join(timeout=5)
    assert seen == ["9.9.9"]

    monkeypatch.setattr(update_check, "fetch_latest_version", lambda url=None: "0.0.1")
    seen.clear()
    update_check.check_in_background(seen.append).join(timeout=5)
    assert seen == []


def test_background_check_survives_a_throwing_callback(monkeypatch):
    monkeypatch.setattr(update_check, "fetch_latest_version", lambda url=None: "9.9.9")

    def boom(_version):
        raise RuntimeError("callback exploded")

    thread = update_check.check_in_background(boom)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_check_thread_is_daemon(monkeypatch):
    # It must never hold the app open at shutdown.
    monkeypatch.setattr(update_check, "fetch_latest_version", lambda url=None: None)
    assert update_check.check_in_background(lambda v: None).daemon is True
