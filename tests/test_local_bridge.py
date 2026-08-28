"""
The in-process bridge, which is the whole Foundry story for a single-machine
setup and so has to work with no .env, no terminal and no hosted service.

Every test here pins down something that was actually broken: the server and
the client disagreeing about the secret, a busy port taking the app down with
it, and CORS rejecting every spelling of "localhost" but one.
"""
import json
import os
import socket

import pytest
import requests

from app.local_bridge_server import PORT_SCAN_RANGE, LocalBridgeServer, lan_address
from bridge_service.app import _is_private_origin


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A throwaway config directory, as if the app had never been run."""
    monkeypatch.setenv("DND_TRACKER_CONFIG_DIR", str(tmp_path))
    for var in ("BRIDGE_TOKEN", "BRIDGE_INGEST_SECRET", "BRIDGE_URL",
                "LOCAL_BRIDGE_HOST", "LOCAL_BRIDGE_PORT", "BRIDGE_HOST", "BRIDGE_PORT"):
        monkeypatch.delenv(var, raising=False)
    import app.settings as settings
    settings._cache = None
    (tmp_path / "settings.json").write_text(json.dumps({
        "foundry_bridge_enabled": True,
        "local_bridge_enabled": True,
    }))
    yield tmp_path
    settings._cache = None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(profile):
    srv = LocalBridgeServer.from_env()
    srv.port = _free_port()
    assert srv.start(), srv.error
    yield srv
    srv.stop()


def test_secret_is_generated_and_persisted(profile):
    """A user who configures nothing still gets a working, protected bridge."""
    srv = LocalBridgeServer.from_env()
    assert srv.token, "no secret was minted"
    stored = json.loads((profile / "settings.json").read_text())
    assert stored["bridge_token"] == srv.token
    # Both halves of the handshake read the same value.
    assert stored["bridge_ingest_secret"] == srv.token


def test_secret_is_stable_across_restarts(profile):
    """Regenerating it every launch would silently break Foundry's copy."""
    first = LocalBridgeServer.from_env().token
    import app.settings as settings
    settings._cache = None
    assert LocalBridgeServer.from_env().token == first


def test_configured_secret_is_not_overwritten(profile):
    """Someone who typed their own secret keeps it."""
    import app.settings as settings
    settings.set("bridge_token", "chosen-by-hand")
    assert LocalBridgeServer.from_env().token == "chosen-by-hand"


def test_server_and_client_agree_on_the_secret(server):
    """The original bug: server read env, client read settings.json, 401.

    The server invented 'local-dev' while the app sent the configured secret,
    so every poll and every snapshot was rejected.
    """
    r = requests.get(f"{server.base_url}/state",
                     headers={"Authorization": f"Bearer {server.token}"}, timeout=5)
    assert r.status_code == 200, r.text


def test_wrong_secret_is_still_rejected(server):
    """Auto-generating a secret must not mean accepting any secret."""
    r = requests.get(f"{server.base_url}/state",
                     headers={"Authorization": "Bearer wrong"}, timeout=5)
    assert r.status_code == 401


def test_round_trip_snapshot_and_command(server):
    """Foundry posts, the app reads, the app commands, Foundry collects."""
    snapshot = {"world": "W", "combat": {"active": True, "round": 2},
                "combatants": [{"name": "Goblin", "tokenId": "t1"}]}
    r = requests.post(f"{server.base_url}/foundry/snapshot",
                      headers={"X-Bridge-Secret": server.token},
                      json=snapshot, timeout=5)
    assert r.status_code == 200, r.text

    r = requests.get(f"{server.base_url}/state",
                     headers={"Authorization": f"Bearer {server.token}"}, timeout=5)
    assert r.json()["combat"]["round"] == 2

    r = requests.post(f"{server.base_url}/commands",
                      headers={"Authorization": f"Bearer {server.token}"},
                      json={"type": "set_hp", "tokenId": "t1", "hp": 3}, timeout=5)
    assert r.status_code == 200, r.text

    r = requests.get(f"{server.base_url}/commands",
                     headers={"X-Bridge-Secret": server.token}, timeout=5)
    commands = r.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["type"] == "set_hp"
    assert commands[0]["payload"]["hp"] == 3


def test_busy_port_moves_to_the_next_one(profile):
    """werkzeug answers EADDRINUSE with sys.exit(1); the app must survive it."""
    port = _free_port()
    hog = socket.socket()
    hog.bind(("127.0.0.1", port))
    hog.listen(1)
    try:
        srv = LocalBridgeServer.from_env()
        srv.port = port
        assert srv.start() is True
        assert srv.port != port, "should have moved to a free port"
        assert srv.error is None
        # And the client is told where it actually landed.
        assert srv.base_url.endswith(str(srv.port))
        srv.stop()
    finally:
        hog.close()


def test_no_free_port_reports_instead_of_exiting(profile):
    """A bridge that cannot start is a degraded app, not a dead one."""
    start = _free_port()
    hogs = []
    try:
        for candidate in range(start, start + PORT_SCAN_RANGE):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", candidate))
                s.listen(1)
                hogs.append(s)
            except OSError:
                s.close()
        srv = LocalBridgeServer.from_env()
        srv.port = start
        assert srv.start() is False
        assert srv.error and "in use" in srv.error
    finally:
        for s in hogs:
            s.close()


def test_base_url_is_never_the_wildcard_address(profile):
    """0.0.0.0 is a valid thing to bind and a meaningless thing to connect to."""
    srv = LocalBridgeServer(host="0.0.0.0", port=8787)
    assert srv.base_url == "http://127.0.0.1:8787"


@pytest.mark.parametrize("origin", [
    "http://localhost:30000",
    "http://127.0.0.1:30000",     # the default that used to be rejected
    "http://192.168.1.50:30000",  # Foundry reached over the LAN
    "http://10.0.0.4:8080",
    "http://[::1]:30000",
])
def test_local_foundry_origins_are_allowed(origin):
    assert _is_private_origin(origin) is True


@pytest.mark.parametrize("origin", [
    "https://foundry.example.com",
    "http://8.8.8.8",
    "ftp://192.168.1.1",
    "",
    None,
])
def test_public_origins_are_not_allowed(origin):
    """Broadening CORS for local use must not open it to the internet."""
    assert _is_private_origin(origin) is False


def test_cors_headers_reach_the_browser(server):
    """The preflight a Foundry browser actually sends."""
    r = requests.options(f"{server.base_url}/foundry/snapshot",
                         headers={"Origin": "http://127.0.0.1:30000",
                                  "Access-Control-Request-Method": "POST"}, timeout=5)
    assert r.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:30000"


def test_lan_address_is_never_loopback():
    """gethostbyname() returns 127.0.1.1 on most Linux boxes -- the wrong answer."""
    found = lan_address()
    assert found is None or not found.startswith("127.")


def test_stop_frees_the_port_for_a_restart(profile):
    """Saving settings tears the bridge down and starts it again.

    If stop() left the socket held, the restart would silently land on the next
    port -- and Foundry, still pointed at the old one, would go quiet with the
    app reporting nothing wrong.
    """
    port = _free_port()
    first = LocalBridgeServer.from_env()
    first.port = port
    assert first.start(), first.error
    assert first.port == port
    first.stop()
    assert first.running is False

    second = LocalBridgeServer.from_env()
    second.port = port
    assert second.start(), second.error
    try:
        assert second.port == port, "restart did not get the same port back"
        r = requests.get(f"{second.base_url}/state",
                         headers={"Authorization": f"Bearer {second.token}"}, timeout=5)
        assert r.status_code == 200
    finally:
        second.stop()


def test_restart_survives_being_called_twice(profile):
    """stop() on an already-stopped server must not raise."""
    srv = LocalBridgeServer.from_env()
    srv.port = _free_port()
    assert srv.start()
    srv.stop()
    srv.stop()
    assert srv.running is False
