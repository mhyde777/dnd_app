# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

D&D 5e Combat Tracker — a PyQt5 desktop application for managing initiative, HP, conditions, and combat state during tabletop sessions. Integrates with Foundry VTT via a Flask-based bridge service for two-way sync.

**Python 3.10 required.** Dependency management via pipenv (`Pipfile`).

## Commands

```bash
# Install dependencies
pipenv install

# Run the app
pipenv run python main.py

# Run tests (use offscreen for headless/CI environments)
pipenv run python -m pytest tests/ -v
QT_QPA_PLATFORM=offscreen pipenv run python -m pytest tests/ -v

# Run a single test file
pipenv run python -m pytest tests/test_initiative_order.py -v

# Run bridge service locally
BRIDGE_TOKEN=changeme BRIDGE_HOST=127.0.0.1 BRIDGE_PORT=8787 pipenv run python -m bridge_service.app

# Package standalone executable
./package.sh          # Linux/macOS
./package_WIN.sh      # Windows (Git Bash)
```

No linter or type checker is configured. Code uses type hints throughout.

## Architecture

```
main.py                         # Entry point, loads .env, launches UI
lib/
  app/
    app.py                      # Application class — central coordinator (~2500 lines)
    creature.py                 # I_Creature dataclass, Player/Monster subclasses
    manager.py                  # CreatureManager — in-memory collection, natural-sort ordering
    save_json.py                # GameState serialization (local JSON persistence)
    config.py                   # Env var configuration (also loads ~/.dnd_tracker_config/.env)
    app_log.py                  # Rotating file log + in-memory ring buffer (Application._log routes here)
    bridge_client.py            # Client for Foundry bridge communication (threading)
    local_bridge_server.py      # In-process bridge server (single-machine mode)
    storage_api.py              # Optional remote storage API
  ui/
    ui.py                       # InitiativeTracker QMainWindow (main UI)
    creature_table_model.py     # QAbstractTableModel for creature table
    windows.py                  # Dialog windows (add/remove combatants, encounters)
    conditions_dropdown.py      # Condition selection widget
    spellcasting_dropdown.py    # Spell slot management widget
    death_saves_dialog.py       # Death saving throws dialog
    enter_initiatives_dialog.py # Initiative roll input dialog
    update_characters.py        # Creature property editor
    notifications.py            # toast() / report_error() / report_warning() + sys.excepthook
    banner.py                   # BannerArea — persistent, keyed, dismissible notifications
    layout_settings_dialog.py   # Panel placement/width config + PANEL_REGISTRY
    log_dialog.py               # Help → Show Log viewer
    toolbar_customize_dialog.py # Two-pane toolbar customizer + TOOLBAR_REGISTRY
    theme.py                    # QSS stylesheet, built from the live palette
    colors.py                   # PALETTE_SCHEMA + user-overridable colour globals
    color_settings_dialog.py    # Colour picker generated from PALETTE_SCHEMA
    icons.py                    # QPainter-drawn toolbar icons (no image assets)
bridge_service/
  app.py                        # Flask REST API for bridge
  command_queue.py              # Command queue with TTL sweeper
foundryvtt-bridge/
  bridge.js                     # Foundry VTT module (JS)
tests/
  test_initiative_order.py
  test_bridge_client.py
  test_command_queue_sweeper.py
```

## Key Design Patterns

- **MVC**: UI layer (`lib/ui/`) talks to Application/Manager (`lib/app/`), which operates on Creature dataclasses.
- **Creatures tracked by name** for stability across HP/state changes. CreatureManager uses natural sort (handles "Goblin 2" < "Goblin 10").
- **Turn order**: initiative DESC, name ASC tiebreaker, computed on-the-fly.
- **`lib/` is an editable package** (`dnd-app-lib`): installed via `pip install -e lib/` or the Pipfile entry. Imports use `from app.X` and `from ui.X`.
- **Two-way Foundry sync**:
  - Foundry → App: combat snapshots posted to bridge, app consumes via SSE stream or polling.
  - App → Foundry: commands (`set_hp`, `set_initiative`, `add_condition`, `remove_condition`) posted to bridge command queue, Foundry polls or streams.
  - Foundry conditions are source of truth — the app derives conditions from snapshot effects, no normalization.
- **Bridge communication runs in background threads** to avoid blocking the Qt event loop. That includes *commands*, not just snapshot polling: `BridgeClient._post_command()` queues and returns, and a single worker drains it (`_post_command_now()` is the blocking body). One worker, FIFO, because order matters — two `next_turn`s must reach Foundry as pressed. It used to POST inline and cost ~460ms of UI-thread time per turn against a remote bridge. Nothing reads the return value; it means "accepted", not "delivered". `closeEvent` calls `flush_commands()` with a timeout, so a last action still goes out but a slow bridge can't hold the window open. **Never add a synchronous network call to a path the UI calls.** Snapshot *polling* had the same fault: `refresh_bridge_state()` ran `fetch_state()` inline on its QTimer, freezing the window every 5s. It now fetches on a worker and returns through `bridge_snapshot_received`, guarded by `_bridge_poll_in_flight` so a slow bridge can't stack a thread per tick.
- **Foundry owns the round only while it has a live combat.** With Foundry closed the bridge keeps serving its last snapshot (`active: false`, `round: 0`), so `_apply_bridge_snapshot()` requires `combat["active"]` *and* `round >= 1` before touching `round_counter`. `max(1, round_value)` silently rewound the tracker to round 1 on every poll.
- **Configuration is environment-driven**: `.env` at repo root + `~/.dnd_tracker_config/.env`. See `lib/app/config.py` for all variables and defaults.
- **Local bridge server** starts in-process by default (`LOCAL_BRIDGE_ENABLED=1`), so single-machine setups need no external bridge.
- **Panel layout is configured, not dragged**: the initiative table is the central widget; "Combat Controls" and "Statblock" are `QDockWidget`s. The saved `panel_layout` dict in `settings.json` (see `lib/ui/layout_settings_dialog.py`) is the source of truth for each panel's side, width and visibility — dock dragging is **disabled by default** and only opt-in via "Let me drag panels around the window". `saveState()`/`restoreState()` are consulted *only* when `allow_drag` is on; otherwise `apply_panel_layout()` places everything declaratively. Adding a panel means adding it to `PANEL_REGISTRY`, `DEFAULT_PANEL_LAYOUT`, and `_dock_for_key()`. Every dock still needs an `objectName` or `saveState()` drops it; bump `LAYOUT_VERSION` in `lib/ui/ui.py` when the set of docks or toolbars changes.
  - **Panel widths are pixel values that must be re-asserted, not set once.** `resizeDocks()` is ignored before the window has been laid out, and Qt hands a growing window's extra width to the docks proportionally — the window manager's maximize is exactly such a resize, which is why widths used to drift a little every session. `_pending_dock_widths` holds the intended width per dock and `_apply_dock_widths()` re-applies it: on show, on every window width change, and for `_LAYOUT_SETTLE_MS` after startup. A dock resize is only taken as *the user's* choice (`_dock_resized` via `_DockResizeWatcher`) when it lands outside `_WINDOW_RESIZE_GRACE` of a window resize; `save_layout()` persists the intended width, never the live one, so a too-narrow window squeezing a dock to its minimum can't make the squeeze permanent.
  - The app always opens maximized (`main.py`). Saved geometry is still restored, as the size the window returns to when un-maximized.
- **The app updates itself by installing beside the running version, never over it**: `<root>/combat-tracker` (launcher) + `<root>/versions/<ver>/` + a `current` file. `lib/app/install_layout.py` locates it, `lib/app/update_install.py` verifies/extracts/installs, `launcher.py` (its own PyInstaller spec) picks the version. A running `.exe` and its loaded DLLs are held open on Windows, and PyInstaller folders load files lazily everywhere, so overwriting an install underneath a live process is a crash waiting to happen — adding a sibling directory avoids the whole problem and leaves the previous version as the rollback. The launcher writes a `launching` marker and `main.py` clears it once a window is up; a stale one means that build failed to start, so the launcher falls back. **Never make the app write into its own version directory**, and keep `launcher.py` dependency-free — it has to start when the app cannot. See `docs/auto-update.md`.
- **Three tiers of error reporting** — never `print()`, since the packaged build runs `console=False` and stdout is discarded:
  1. `notify(msg, level)` / `toast(...)` — transient confirmations that auto-dismiss ("State saved").
  2. `show_banner(key, msg, level, action_label, action)` / `clear_banner(key)` — persistent, non-blocking strip above the table for conditions that outlive a toast (bridge disconnected). Keyed, so re-showing updates in place instead of stacking.
  3. `report_error(parent, title, msg, exc)` — blocking modal with the traceback under "Show Details", for when the requested action did not happen.
  Uncaught exceptions reach a dialog via the excepthook installed in `main.py`. `self._log(...)` infers severity from an `[ERROR]`/`[WARN]`/`[DBG]` prefix.
- **Customizable toolbar**: add a new action by putting it in `TOOLBAR_REGISTRY` (`lib/ui/toolbar_customize_dialog.py`) *and* in `_toolbar_action_map` (`lib/ui/ui.py`) — the ids must match. Give it an icon by adding the id to `ACTION_GLYPHS` in `lib/ui/icons.py`; an action with no entry stays text-only **on purpose** — a misleading icon is worse than none. Icons are drawn with `QPainter`, not `QStyle.standardIcon` (which renders differently per platform/theme) and not bundled image files.
- **Keyboard shortcuts are user-rebindable**: `SHORTCUT_SCHEMA` in `lib/ui/shortcut_settings_dialog.py` holds the ids, labels and defaults; `settings.json` stores only what the user changed, so a new default still reaches anyone who never touched that binding. A new shortcut needs an entry there *and* in `_shortcut_targets()` (`lib/ui/ui.py`) — matching ids, same contract as the toolbar registry. Never call `setShortcut()`/`QShortcut(key, ...)` at construction: `apply_shortcuts()` is the only place sequences are bound, and it runs again whenever the customizer saves. Anything that quotes a sequence in a tooltip belongs in `_refresh_shortcut_hints()`, or it goes stale after a rebind.
- **Colours are user-overridable**: `lib/ui/colors.py` holds `PALETTE_SCHEMA` (the shipped values are the defaults) and rebinds its module globals in `apply()`. **Consumers must use attribute access** — `colors.HP_LOW_ACTIVE`, never `from ui.colors import HP_LOW_ACTIVE`, which binds once at import and would never see a user change. Adding a colour to `PALETTE_SCHEMA` is all that's needed for it to appear in the colour dialog. `InitiativeTracker.refresh_theme()` re-applies the stylesheet, redraws icons and repaints the table; it caches the underlying qdarktheme QSS as `app._base_stylesheet` so repeated refreshes don't stack copies.
- **Active-turn row highlight**: `CreatureTableModel._row_background()` is the single authority on a row's colour. It resolves the whole row *before* any per-cell tint, always returns a colour for the active creature (even when HP is untracked), and falls back to the zebra stripe last. Action/bonus/reaction cell tinting is opt-in (`colors.tint_action_cells()`, off by default) since the ✔/✘ glyph already carries that state.
  - **Never call `QTableView.setAlternatingRowColors(True)` here.** Qt paints the alternate row background *over* the model's `BackgroundRole`, which silently hides the active-turn highlight on every second row — the highlight appears to flicker on and off as turns advance. Zebra striping was tried and deliberately removed; the table has no row banding by design.
  - When verifying row colours, sample **painted pixels** from `table.viewport().grab()`, not just `model.data(..., BackgroundRole)` — the model can be correct while the view paints something else. Sample above/below the text baseline or take the modal colour across the row; sampling mid-row hits anti-aliased glyph pixels and gives false failures. Note `_type` is a hidden column with width 0, so `columnViewportPosition(0)` lands inside the name column.
