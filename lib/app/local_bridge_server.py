"""
The bridge, running inside the app.

Someone whose Foundry and tracker are on one PC should not have to stand up a
web service, pick a port or edit a dotfile to get sync working. This starts the
same Flask app `bridge_service` serves standalone, on a background thread, and
hands back the URL it actually reached.

Two things this module is careful about, both learned the hard way:

* **The server and the client have to agree on the secret.** `create_app()`
  reads its credentials from the environment, while the app and the Foundry
  module read theirs from settings.json. Nothing kept those in step, so a user
  who typed a secret into the Settings dialog got 401 on every request from
  both sides. `_export_env()` is now the single point where resolved
  configuration becomes the environment the server sees.
* **A busy port must not take the app down with it.** werkzeug's
  `make_server()` answers EADDRINUSE by calling `sys.exit(1)`, which inside
  `Application.__init__` means the window never opens -- and in the packaged
  `console=False` build, with no message anywhere. We probe ports ourselves and
  surface a failure as a value the caller can put in a banner.
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from threading import Thread
from typing import Optional

from werkzeug.serving import make_server

from app.app_log import get_logger

#: How many consecutive ports to try before giving up.
PORT_SCAN_RANGE = 10


def _log(message: str) -> None:
    """Bridge chatter goes to the app log; the packaged build has no stdout."""
    text = message.lower()
    level = 30 if any(w in text for w in ("failed", "error", "could not", "busy")) else 20
    get_logger().log(level, "%s", message)


def _port_is_free(host: str, port: int) -> bool:
    """Whether we could bind here, asked without werkzeug's exit-on-failure."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def lan_address() -> Optional[str]:
    """This machine's address on the local network, or None.

    Asked of the routing table rather than of DNS: `gethostbyname(hostname)`
    returns 127.0.1.1 on most Linux boxes, which is exactly the wrong answer to
    print in "point Foundry at this". No packet is actually sent -- connecting
    a UDP socket only picks the interface that would carry one.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 1))  # TEST-NET-1: routable, never routed
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return address if address and not address.startswith("127.") else None


@dataclass
class LocalBridgeServer:
    host: str = "127.0.0.1"
    port: int = 8787
    token: str = ""
    allow_local_origins: bool = True
    #: Set when start() could not bind anywhere, for the caller to display.
    error: Optional[str] = None
    _thread: Optional[Thread] = field(default=None, repr=False)
    _server: Optional[object] = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "LocalBridgeServer":
        """Build from settings.json, falling back to env vars then defaults.

        Named for the API it has always had. It is no longer the environment
        alone: `config.bridge_value()` consults the Settings dialog first, so
        the server matches whatever the user configured in the GUI.
        """
        from app.config import (
            ensure_bridge_secret,
            local_bridge_host,
            local_bridge_port,
        )

        return cls(
            host=local_bridge_host(),
            port=local_bridge_port(),
            token=ensure_bridge_secret(),
        )

    @property
    def base_url(self) -> str:
        """The URL the app's own client should talk to.

        Always loopback: 0.0.0.0 means "every interface", which is a valid
        thing to bind and a meaningless thing to connect to.
        """
        host = "127.0.0.1" if self.host in ("0.0.0.0", "", "::") else self.host
        return f"http://{host}:{self.port}"

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _export_env(self) -> None:
        """Publish resolved config where `create_app()` will look for it.

        The Flask app is configured entirely through `os.getenv`. Writing the
        values here -- rather than letting each side read its own source -- is
        what stops the server and the client disagreeing about the secret.
        """
        if self.token:
            os.environ["BRIDGE_TOKEN"] = self.token
            # Foundry authenticates its posts with X-Bridge-Secret rather than
            # a bearer token. Keeping the two equal means one value to paste.
            os.environ["BRIDGE_INGEST_SECRET"] = self.token
        os.environ["BRIDGE_ALLOW_LOCAL_ORIGINS"] = "1" if self.allow_local_origins else "0"

    def start(self) -> bool:
        """Start serving, returning whether it came up.

        Never raises for an unavailable port and never exits the process: a
        bridge that cannot start is a degraded app, not a dead one.
        """
        if self.running:
            return True
        self.error = None
        self._export_env()

        from bridge_service.app import create_app

        app = create_app()
        wanted = self.port
        for candidate in range(wanted, wanted + PORT_SCAN_RANGE):
            if not _port_is_free(self.host, candidate):
                continue
            try:
                self._server = make_server(self.host, candidate, app, threaded=True)
            except (OSError, SystemExit):
                # Lost the race between probing and binding, or werkzeug tried
                # to exit on us. Either way, move along.
                continue
            self.port = candidate
            self._thread = Thread(
                target=self._server.serve_forever,
                name="local-bridge",
                daemon=True,
            )
            self._thread.start()
            if candidate != wanted:
                _log(f"[Bridge] Port {wanted} was busy; local bridge is on {candidate}.")
            _log(f"[Bridge] Local bridge listening on http://{self.host}:{self.port}")
            return True

        self._server = None
        self.error = (
            f"Could not start the local bridge: ports {wanted}-{wanted + PORT_SCAN_RANGE - 1} "
            f"on {self.host} are all in use."
        )
        _log(f"[Bridge] {self.error}")
        return False

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception as exc:  # pragma: no cover - shutdown is best effort
                _log(f"[Bridge] Local bridge shutdown failed: {exc}")
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
