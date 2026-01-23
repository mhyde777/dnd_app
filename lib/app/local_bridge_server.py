import os
from dataclasses import dataclass
from threading import Thread
from typing import Optional

from werkzeug.serving import make_server

from bridge_service.app import create_app


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


@dataclass
class LocalBridgeServer:
    host: str = "127.0.0.1"
    port: int = 8787
    _thread: Optional[Thread] = None
    _server: Optional[object] = None

    @classmethod
    def from_env(cls) -> "LocalBridgeServer":
        host = _env("LOCAL_BRIDGE_HOST", _env("BRIDGE_HOST", "127.0.0.1"))
        port = int(_env("LOCAL_BRIDGE_PORT", _env("BRIDGE_PORT", "8787")))
        return cls(host=host, port=port)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        app = create_app()
        self._server = make_server(self.host, self.port, app, threaded=True)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[Bridge] Local bridge server running on http://{self.host}:{self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
