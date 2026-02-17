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
    bridge_client.py            # Client for Foundry bridge communication (threading)
    local_bridge_server.py      # In-process bridge server (single-machine mode)
    player_view_server.py       # HTTP server for player-visible combat data
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
- **Bridge communication runs in background threads** to avoid blocking the Qt event loop.
- **Configuration is environment-driven**: `.env` at repo root + `~/.dnd_tracker_config/.env`. See `lib/app/config.py` for all variables and defaults.
- **Local bridge server** starts in-process by default (`LOCAL_BRIDGE_ENABLED=1`), so single-machine setups need no external bridge.
- **Player View**: optional HTTP server (port 5001) serving an iframe-friendly page with public-only combat data.
