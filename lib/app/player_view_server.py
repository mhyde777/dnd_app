import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse


def _render_player_view_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Player View</title>
    <style>
      :root {
        color-scheme: dark;
        --bg: #141414;
        --fg: #f2f2f2;
        --muted: #a6a6a6;
        --accent: #7ad7ff;
        --border: #2f2f2f;
        --highlight: #1f3b4d;
      }
      body {
        margin: 0;
        font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        background: var(--bg);
        color: var(--fg);
      }
      .wrap {
        padding: 16px 20px 24px;
      }
      .header {
        display: flex;
        flex-wrap: wrap;
        gap: 12px 24px;
        align-items: center;
        border-bottom: 1px solid var(--border);
        padding-bottom: 12px;
        margin-bottom: 16px;
      }
      .stat {
        font-size: 18px;
        font-weight: 600;
      }
      .stat span {
        color: var(--accent);
      }
      .badge {
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        padding: 4px 8px;
        border-radius: 999px;
        border: 1px solid var(--border);
        color: var(--muted);
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 15px;
      }
      th, td {
        padding: 10px 12px;
        border-bottom: 1px solid var(--border);
        text-align: left;
        vertical-align: top;
      }
      th {
        color: var(--muted);
        font-weight: 600;
        text-transform: uppercase;
        font-size: 12px;
        letter-spacing: 0.08em;
      }
      tr.highlight {
        background: var(--highlight);
      }
      .empty {
        color: var(--muted);
        font-style: italic;
        padding: 12px 0;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="header">
        <div class="stat" id="round">Round: <span>--</span></div>
        <div class="stat" id="time">Time: <span>--</span></div>
        <div class="stat" id="current">Current: <span>--</span></div>
        <div class="badge" id="live-indicator">Live</div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Init</th>
            <th>Conditions</th>
            <th>Public Notes</th>
          </tr>
        </thead>
        <tbody id="combatants"></tbody>
      </table>
      <div class="empty" id="empty" style="display: none;">No visible combatants.</div>
    </div>
    <script>
      const roundEl = document.getElementById("round");
      const timeEl = document.getElementById("time");
      const currentEl = document.getElementById("current");
      const indicatorEl = document.getElementById("live-indicator");
      const bodyEl = document.getElementById("combatants");
      const emptyEl = document.getElementById("empty");

      function setText(node, label, value) {
        node.innerHTML = label + ": <span>" + value + "</span>";
      }

      function render(data) {
        if (!data) return;
        setText(roundEl, "Round", data.round ?? "--");
        setText(timeEl, "Time", (data.time ?? "--") + "s");
        if (data.current_hidden) {
          setText(currentEl, "Current", "(Hidden)");
        } else {
          setText(currentEl, "Current", data.current_name || "--");
        }

        indicatorEl.textContent = data.live ? "Live" : "Paused";
        indicatorEl.style.color = data.live ? "#7ad7ff" : "#f5c16c";

        bodyEl.innerHTML = "";
        if (!data.combatants || data.combatants.length === 0) {
          emptyEl.style.display = "block";
          return;
        }
        emptyEl.style.display = "none";
        data.combatants.forEach((c) => {
          const row = document.createElement("tr");
          if (data.current_name && c.name === data.current_name && !data.current_hidden) {
            row.classList.add("highlight");
          }
          const nameCell = document.createElement("td");
          nameCell.textContent = c.name || "";
          const initCell = document.createElement("td");
          initCell.textContent = c.initiative ?? "";
          const condCell = document.createElement("td");
          condCell.textContent = c.conditions || "";
          const notesCell = document.createElement("td");
          notesCell.textContent = c.public_notes || "";
          row.appendChild(nameCell);
          row.appendChild(initCell);
          row.appendChild(condCell);
          row.appendChild(notesCell);
          bodyEl.appendChild(row);
        });
      }

      async function refresh() {
        try {
          const resp = await fetch("/player.json", { cache: "no-store" });
          if (!resp.ok) return;
          const data = await resp.json();
          render(data);
        } catch (err) {
          // ignore transient errors
        }
      }

      refresh();
      setInterval(refresh, 1000);
    </script>
  </body>
</html>
"""


class PlayerViewServer:
    def __init__(self, state_provider: Callable[[], Dict[str, Any]]):
        self.state_provider = state_provider
        self._thread: Optional[Thread] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self.host = os.getenv("PLAYER_VIEW_HOST", "0.0.0.0")
        self.port = int(os.getenv("PLAYER_VIEW_PORT", "5001"))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        handler = self._build_handler()
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError as exc:
            print(f"[PlayerView] Failed to start server on {self.host}:{self.port} ({exc})")
            self._server = None
            return

        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[PlayerView] Serving on http://{self.host}:{self.port}/player")

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None

    def _build_handler(self):
        state_provider = self.state_provider
        html = _render_player_view_html().encode("utf-8")

        class PlayerViewHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = urlparse(self.path).path.rstrip("/")

                if path == "/player":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return

                if path == "/player.json":
                    try:
                        payload = state_provider()
                    except Exception as exc:
                        print(f"[PlayerView] Failed to build JSON payload: {exc}")
                        payload = {
                            "round": 1,
                            "time": 0,
                            "current_name": None,
                            "current_hidden": False,
                            "combatants": [],
                            "live": False,
                        }
                    body = json.dumps(payload).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not Found")

            def log_message(self, format, *args):
                return

        return PlayerViewHandler
