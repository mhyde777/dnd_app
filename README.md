# Dungeons & Dragons Combat Tracker

## Dependecy management
This project uses **pipenv** as the primary dependency manager, driven by the `Pipfile`. A minimal `requirements.txt` is also provided for environments that prefer `pip`, and it includes the editable install of the local `lib/` directory (`dnd-app-lib`).
## Setup and running the app 
### Windows (Git Bash) notes
* The app reads a `.env` from the repo root (next to `main.py`) **and** from `~/.dnd_tracker_config/.env`. The home directory `~` resolves inside Git Bash, so you can keep a shared config in `C:\Users\<you>\.dnd_tracker_config\.env` if desired. The first load happens in `main.py`, and the config folder load happens in `lib/app/config.py`. 
* Use `source` to activate virtualenvs in Git Bash, and prefer `python -m venv` (works on Windows).
* When pointing to services on your server, use the same URLs you already use on Linux/macOS (e.g., `https://bridge.masonhyde.com`). Windows does not require any special formatting beyond valid URLs.

### Option A: pipenv (recommended)
1. Install pipenv if needed: `pip install --user pipenv`
2. Install dependencies and create the virtual environment (Python 3.10 recommended):
    ```bash
    pipenv install
    ```
3. Run the application:
    ```bash
    pipenv run python main.py 
    ```

### Option B: pip (alternative)
1. Create a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```
2. Install dependencies with pip:
    ```bash
    pip install --upgrade pip
    pip install -r requirements.txt
    ```
3. Launch the application:
    ```bash
    python main.py 
    ```

## Packaging the app {PyInstaller}
The packagin flow builds a standalone binary and Linux or Windows application folder layout.

1. Install dependencies (including PyIntsaller):
    ```bash
    pip install -r requirements.txt pyinstaller 
    ```
2. Build the executable and package directory:
    ```bash
    ../package.sh    
    ```
    or, on Windows (Git-Bash):
    ```bash
    ./package_WIN.sh
    ```
3. The bundled app is availalbe at:
    ```text
    dist/combat_tracker/
    ```
    A Linux-ready folder layout is staged at:
    ```text
    package/
    ```
    A Windows-readh folder layout is staged at:
    ```text
    package_win/
    ```

## Storage API Configuration
The app can optionally persist encounters to a storage API. Configuration is controlled by two environmental variables (e.g., in a `.env` file next to `main.py`):

* `USE_STORAGE_API_ONLY` - When truthy (`1`, `true`, etc.), the app routes all save/load flows through the storage API instead of local JSON files. Defaults to `0` (local files).
* `STORAGE_API_BASE` - Base URL of the Storage serves, such as `http://127.0.0.1:8000`. This is required when `USE_STORAGE_API_ONLY` is enabled.

### Example `.env` snippets

**Local files (default, no Storage service):**
```
USE_STORAGE_API_ONLY=0
```

**Storage API enabled:**
```
USE_STORAGE_API_ONLY=1 
STORAGE_API_BASE=http://127.0.0.1:800
```

**Storage API enabled (remote server example):**
```
USE_STORAGE_API_ONLY=1
STORAGE_API_BASE=https://your-storage-api.example.com
STORAGE_API_KEY=your_api_key_if_required
```

### Running without the Storage service

Leave `USE_STORAGE_API_ONLY` unset (or set it to `0`) to kep using the built-in local JSOn files. If you enable `USE_STORAGE_API_ONLY` without providing `STORAGE_API_BASE`, the app will start but show a warning explaining how the to fix the configuration so you are not blocked while the Storage service is offline.

## Player View (Foundry-friendly)
When enabled, the app launches a lightweight Player View web page that can be embedded in Foundry via Inline Webviewer. The page is designed to be iframe-friendly and shows only player-safe combat data.

**Access the Player View:**
* Default URL: `http://127.0.0.1:5001/player`
* JSON feed: `http://127.0.0.1:5001/player.json`
* Optional environment overrides:
  * `PLAYER_VIEW_ENABLED` (default `0`, set to `1` to enable)
  * `PLAYER_VIEW_HOST` (default `0.0.0.0`)
  * `PLAYER_VIEW_PORT` (default `5001`)

**Foundry Inline Webviewer embed:**
1. Install/enable the Inline Webviewer module in Foundry.
2. Add a Webviewer element and set the URL to your Player View route (example: `http://127.0.0.1:5001/player`).
3. Resize as needed; the page is fully self-contained and iframe-friendly.

**Visibility + Live Updates behavior:**
* Right-click a combatant row in the initiative table to open the context menu (best on the name cell).
* Monsters cen be **Hidden/Revealed** from the Player View via the "Hide from Player View" / "Reveal to Player view" actions
* The initiative table shows a compact **Notes** column for short flags. Use **Edit Public Notes...** / **Edit Private Notes...** in the context menu for longer notes.
* The Player View only displays **Public Notes** (never Private Notes)
* The **Live Updates** toggle pauses/resumes the Player View. When paused, the page freezes on the last published snapshot even if the DM continues editing.

**Downed display (Player View only)**
* By default, downed combatants (current HP of 0) stay visible and recieve a red highlight.
* To hide down monsters instead, set `PLAYER_VIEW_HIDE_DOWNED=1` (players remain visible even when downed).

## Foundry → Bridge → App (Phase 1: snapshot sync)

This repo includes a minimal bridge service and a Foundry module for sending combat snapshots to the bridge. The app fetches the latest snapshot from the bridge and mirrors Foundry initiative, turn state, and conditions. Foundry conditions are the source of truth: the app derives conditions only from the snapshot effects list and does not normalize or rename them.

### Bridge service

**Environment variables:**
* `BRIDGE_HOST` (default `127.0.0.1`)
* `BRIDGE_PORT` (default `8787`)
* `BRIDGE_TOKEN` (**required** for external access to `/state`, `/health`, `/version`)
* `BRIDGE_INGEST_SECRET` (optional shared secret for Foundry → bridge POSTs)
* `BRIDGE_SNAPSHOT_PATH` (optional file path to persist the latest snapshot)
* `BRIDGE_COMMANDS_PATH` (optional file path to persist queued commands)
* `BRIDGE_VERSION` (optional version string for `/version`)
* `COMMAND_TTL_SECONDS` (optional; default `60`)
* `COMMAND_SWEEP_INTERVAL_SECONDS` (optional; default `5`)
* `BRIDGE_STREAM_KEEPALIVE_SECONDS` (optional; default `15`)

**Example `.env` for a remote bridge (app + bridge):**
```
# App-side config
BRIDGE_URL=https://bridge.masonhyde.com
BRIDGE_TOKEN=your_bridge_token

# Bridge-side config (set on the bridge server)
BRIDGE_HOST=0.0.0.0
BRIDGE_PORT=8787
BRIDGE_TOKEN=your_bridge_token
BRIDGE_INGEST_SECRET=your_shared_secret
```

**Run locally (pipenv):**
```bash
pipenv install
BRIDGE_TOKEN=changeme BRIDGE_HOST=127.0.0.1 BRIDGE_PORT=8787 pipenv run python -m bridge_service.app
```

**Run locally (venv/pip):**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
BRIDGE_TOKEN=changeme BRIDGE_HOST=127.0.0.1 BRIDGE_PORT=8787 python -m bridge_service.app
```

**Quick curl test:**
```bash
export BRIDGE_TOKEN=changeme
curl -H "Authorization: Bearer ${BRIDGE_TOKEN}" http://127.0.0.1:8787/health
curl -H "Authorization: Bearer ${BRIDGE_TOKEN}" http://127.0.0.1:8787/state
```

**Systemd unit template:**
See `deploy/bridge.service` for a sample unit. Create `/etc/dnd_app/bridge.env` for environment values.

### Foundry module

Module folder: `foundryvtt-bridge/`

**Install:**
1. Copy `foundryvtt-bridge/` into your Foundry `Data/modules/` folder.
2. Enable **Foundry Bridge Sync** in your world.
3. In **Module Settings**, confirm the Bridge URL (default `http://127.0.0.1:8787`) and optional shared secret.

The module posts a full combat snapshot to `http://127.0.0.1:8787/foundry/snapshot` on combat/turn/HP/effect changes.

### Python app client

Set these environment variables (for the app process):
* `BRIDGE_URL` (default `http://127.0.0.1:8787`)
* `BRIDGE_TOKEN` (required to fetch `/state` and enqueue `/commands`)
* `BRIDGE_STREAM_ENABLED` (default `1`, use `/state/stream` SSE instead of polling `/state`)

On startup the app logs bridge sync status and prints the snapshot count when it loads.

### Snapshot JSON schema

```json
{
  "source": "foundry",
  "world": "<world name>",
  "timestamp": "<iso8601>",
  "combat": {
    "active": true,
    "id": "<combatId or null>",
    "round": 1,
    "turn": 0,
    "activeCombatant": {
      "combatantId": "<combatantId or null>",
      "tokenId": "<id>",
      "actorId": "<id>",
      "name": "<string>",
      "initiative": 12
    }
  },
  "combatants": [
    {
      "combatantId": "<combatantId or null>",
      "tokenId": "<id>",
      "actorId": "<id>",
      "name": "<string>",
      "initiative": 12,
      "hp": { "value": 10, "max": 15 },
      "effects": [
        {
          "id": "<activeEffectId>",
          "label": "<foundry label>",
          "icon": "<icon url or null>",
          "disabled": false,
          "origin": "<origin or null>"
        }
      ]
    }
  ]
}
```

## App → Foundry (Phase 2: command queue)

The bridge supports an app-to-Foundry command queue via `POST /commands`. When the app edits current HP or conditions for a combatant that matches a Foundry combatant, it posts commands to the bridge and Foundry polls the queue. Additional commands include `set_initiative`, `add_condition`, and `remove_condition`.
When enabled in the Foundry module settings, Foundry can keep a persistent EventSource connection to `/commands/stream` for lower latency.

**Foundry module settings:**
* `Use command stream (EventSource)` toggles a persistent stream instead of polling.

**App environment variables:**
* `BRIDGE_URL` (default `http://127.0.0.1:8787`)
* `BRIDGE_TOKEN` (required to enqueue `/commands`)

**Bridge environment variables:**
* `BRIDGE_TOKEN` (required to authorize `/commands`)
* `BRIDGE_COMMANDS_PATH` (optional; defaults to `/var/lib/dnd-bridge/commands.json`)
* `BRIDGE_INGEST_SECRET` (required for Foundry polling `/commands` and `/commands/<id>/ack`)
* `COMMAND_TTL_SECONDS` (optional; default `60`)
* `COMMAND_SWEEP_INTERVAL_SECONDS` (optional; default `5`)

## Local bridge server (single-machine mode)
By default, the desktop app can start a local bridge server inside the app process. This keeps snapshots, commands, and storage local by default.

**Environment variables:**
* `LOCAL_BRIDGE_ENABLED` (default `1`, set to `0` to disable)
* `LOCAL_BRIDGE_HOST` (default `127.0.0.1`)
* `LOCAL_BRIDGE_PORT` (default `8787`)

If `BRIDGE_TOKEN` is not set, the app defaults it to `local-dev` and also uses that value for `BRIDGE_INGEST_SECRET`. Configure your Foundry module to use the same shared secret.


### Manual test checklist

1. Start the bridge service locally with `BRIDGE_TOKEN` set.
2. Use the curl test above to confirm `/health` and `/state` respond.
3. Install/enable the Foundry module and start combat; verify bridge logs show snapshot receipt.
4. Verify snapshots include `combatantId` and the full `effects[]` list for combatants.
5. Add/remove a condition in Foundry and confirm the app mirrors the snapshot effects list.
6. In the app, toggle a condition from the conditions dropdown and verify it appears in Foundry.
7. Run the dev helper to exercise `add_condition`, `remove_condition`, and `set_initiative`:
   ```bash
   PYTHONPATH=lib BRIDGE_URL=http://127.0.0.1:8787 BRIDGE_TOKEN=changeme \
     BRIDGE_TEST_CONDITION_LABEL="Prone" python -m app.bridge_dev
   ```
8. Verify the condition add/remove and initiative changes in Foundry, and confirm the command queue drains/acks.
