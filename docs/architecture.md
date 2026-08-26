# Architecture

How the app is put together, and the decisions that are easy to undo by
accident. Written for anyone changing the code — including me in six months.

If you only read one section, read [Invariants](#invariants). Most of those are
there because the alternative was tried and caused a bug that was hard to find.

---

## The shape of it

A PyQt5 desktop app. Python 3.10, dependencies via pipenv.

```
main.py                    entry point: theme, first-run wizard, main window
launcher.py                separate tiny binary; picks which version to run
lib/
  app/                     everything that isn't a widget
  ui/                      everything that is
bridge_service/            Flask service Foundry and the app both talk to
storage_service/           reference storage server (optional, not required)
foundryvtt-bridge/         the Foundry module (JavaScript)
tests/
```

`lib/` is an editable package (`dnd-app-lib`), so imports are `from app.X` and
`from ui.X` rather than `from lib.app.X`.

**Roughly MVC.** `lib/ui/` talks to `Application` and `CreatureManager` in
`lib/app/`, which operate on `Creature` dataclasses. The seam is not perfectly
clean — `InitiativeTracker` inherits from both `QMainWindow` and `Application`,
so `self` is both the window and the application object. Worth knowing before
you go looking for where one ends and the other begins.

### The core objects

| | |
|---|---|
| `I_Creature` (`app/creature.py`) | Base dataclass. `Player` and `Monster` subclass it. `to_dict()`/`from_dict()` handle persistence — use `.get()` with defaults when adding fields, or old saves break. |
| `CreatureManager` (`app/manager.py`) | The in-memory collection. Owns ordering. |
| `Application` (`app/app.py`) | The coordinator. Large (~3000 lines); the place most behaviour lives. |
| `InitiativeTracker` (`ui/ui.py`) | The main window. Builds the widgets, owns the layout. |
| `CreatureTableModel` (`ui/creature_table_model.py`) | `QAbstractTableModel` over the manager. |

**Creatures are tracked by name.** Names are the identity, which is what keeps
references stable as HP and state change. `CreatureManager` sorts naturally, so
"Goblin 2" comes before "Goblin 10" rather than after it.

**Turn order** is initiative descending, name ascending as the tiebreaker,
computed on the fly rather than stored.

---

## The UI layout model

The initiative table is the central widget. "Combat Controls" and "Statblock"
are `QDockWidget`s.

**Layout is configured, not dragged.** The `panel_layout` dict in
`settings.json` is the source of truth for each panel's side, width and
visibility. Dock dragging is off by default and opt-in via *"Let me drag panels
around the window"*; `saveState()`/`restoreState()` are consulted **only** when
that is on. Otherwise `apply_panel_layout()` places everything declaratively.

The reason is that a dragged layout is easy to knock out of shape by accident
and hard to put back precisely, and Qt's saved state is opaque when it goes
wrong.

**Panel widths are pixel values that must be re-asserted, not set once.**
`resizeDocks()` is ignored before the window has been laid out, and Qt hands a
growing window's extra width to the docks proportionally — the window manager's
maximize is exactly such a resize, which is why widths used to drift a little
every session. `_pending_dock_widths` holds the intended width and
`_apply_dock_widths()` re-applies it: on show, on every window width change,
and for a settle period after startup. A dock resize counts as *the user's*
choice only when it lands outside a grace window after a window resize, and
`save_layout()` persists the intended width rather than the live one — so a
too-narrow window squeezing a dock to its minimum cannot make the squeeze
permanent.

### Table sizing

The table is sized to its contents in both directions, capped by what the
layout can give it:

- `_fit_table_height()` / `_fit_table_width()` set a **maximum**, never a
  minimum. A minimum would raise the window's `minimumSizeHint` and stop a
  long initiative order from being shrunk.
- The table keeps `stretch=1` with an expanding spacer after it. Capping
  without the stretch factor pins it to its size hint regardless of content.
- `_stretch_notes_column()` gives leftover width to Notes, and measures the
  space from the *container*, not the table's own viewport — the viewport is
  capped to the columns, so asking it would only echo back what the columns
  already have and a widened window would never be filled.
- Whether a horizontal scrollbar is needed is derived from the column widths,
  not from `horizontalScrollBar().isVisible()`, which Qt updates a layout pass
  late and which therefore reports the previous state right after a change.

---

## Registries

Several features are extended by adding an entry to a registry rather than by
editing several places. In each case the ids must match across both halves.

| Feature | Registry | Also needs |
|---|---|---|
| Toolbar action | `TOOLBAR_REGISTRY` (`ui/toolbar_customize_dialog.py`) | `_toolbar_action_map` in `ui/ui.py`; an icon in `ACTION_GLYPHS` (`ui/icons.py`) is optional |
| Keyboard shortcut | `SHORTCUT_SCHEMA` (`ui/shortcut_settings_dialog.py`) | `_shortcut_targets()` in `ui/ui.py` |
| Panel | `PANEL_REGISTRY`, `DEFAULT_PANEL_LAYOUT` (`ui/layout_settings_dialog.py`) | `_dock_for_key()` in `ui/ui.py`, and an `objectName` on the dock |
| Combat Controls section | `CONTROL_SECTION_REGISTRY` (`ui/control_sections_dialog.py`) | `_control_sections` in `ui/ui.py` |
| Colour | `PALETTE_SCHEMA` (`ui/colors.py`) | nothing — it appears in the colour dialog automatically |

Bump `LAYOUT_VERSION` in `ui/ui.py` when the set of docks or toolbars changes,
or `restoreState()` will silently reject saved layouts.

---

## Foundry sync

Three pieces, and the middle one is separate from both others: the app, the
**bridge** (`bridge_service/`, a small Flask service), and the **Foundry
module** (`foundryvtt-bridge/`). Neither end talks to the other directly.

- **Foundry → app:** Foundry posts combat snapshots to the bridge. The app
  consumes them by SSE stream or by polling every five seconds.
- **App → Foundry:** commands (`set_hp`, `set_initiative`, `add_condition`,
  `remove_condition`, turn changes) go onto the bridge's command queue, which
  Foundry polls or streams.

Foundry's conditions are the source of truth; the app derives conditions from
snapshot effects without normalising them.

A **local bridge server** can run in-process, which is what makes a
single-machine setup need nothing installed or hosted. It is opt-in — *Run the
bridge on this computer* in the settings dialog — because binding a port is
wrong on the machine of someone who does not use Foundry at all.

`LocalBridgeServer` owns three things that are easy to get wrong:

- **It is the single point where configuration becomes the server's
  environment.** `bridge_service.create_app()` reads its credentials from
  `os.getenv`, while the app and Foundry read theirs from `settings.json`.
  Nothing kept those in step, so a secret typed into the dialog produced 401 on
  every request from both directions. `_export_env()` now publishes the
  resolved values before the app is created, and `Application` points its
  client at `local_bridge.base_url` rather than at a possibly stale
  `BRIDGE_URL`.
- **A busy port must not be fatal.** werkzeug's `make_server()` answers
  EADDRINUSE by calling `sys.exit(1)`; raised inside `Application.__init__`
  that meant no window at all, and in the `console=False` build, no message
  either. Ports are probed first and scanned forward, and a total failure
  becomes `local_bridge_error` for the UI to put in a banner.
- **The secret is generated, not demanded.** `config.ensure_bridge_secret()`
  mints one on first use and persists it, so the user's only job is to copy it
  into Foundry. It is never regenerated — that would silently break Foundry's
  saved copy.

See [foundry-setup.md](foundry-setup.md) for the user-facing side.

---

## Storage and settings

Two different things in two different places:

- **Settings** — `~/.dnd_tracker_config/settings.json`, written 0600 because it
  holds the storage API key and the Foundry secret. `app/settings.py` reads and
  writes it; `app/config.py` checks it first and falls back to environment
  variables for backward compatibility.
- **Content** — encounters, statblocks, spells, items. Either `LocalStorage`
  (a directory of JSON) or `StorageAPI` (an HTTP service). Both present the
  same interface, and `app.storage_api` is always one of them.

`settings_sync.py` carries the portable half of settings between machines
through whichever storage is configured. **`SYNCABLE_KEYS` is an allowlist on
purpose** — settings.json holds secrets, and a denylist would leak the next one
somebody adds and forgets about.

---

## Updating

The app installs a new version *beside* the running one and repoints a
`current` file, rather than overwriting anything:

```
<root>/combat-tracker      the launcher — what shortcuts point at
<root>/versions/<ver>/     a whole PyInstaller build
<root>/current             which version to run
```

A running `.exe` and its loaded DLLs are held open on Windows, and PyInstaller
folders load files lazily everywhere, so overwriting an install underneath a
live process is a crash waiting to happen. Adding a sibling directory avoids
that entirely, and leaves the previous version as the way back.

The launcher writes a `launching` marker before starting a version and the app
clears it once a window is up. A marker still there on the next start means
that build failed, so the launcher falls back to the previous one. After an
update the new build runs a self-check (`app/self_test.py`); passing retires
the version it replaced, failing keeps it and offers to go back.

Full detail in [auto-update.md](auto-update.md).

---

## Invariants

Things that look harmless and are not.

**Never call `QTableView.setAlternatingRowColors(True)`.** Qt paints the
alternate row background *over* the model's `BackgroundRole`, which silently
hides the active-turn highlight on every second row — it looks like the
highlight flickers on and off as turns advance. Zebra striping was tried and
deliberately removed; the table has no row banding by design.

**Never add a synchronous network call to a path the UI calls.** Both halves of
the bridge got this wrong and both froze the window: commands POSTed inline
cost ~460ms per turn against a remote bridge, and snapshot polling ran its HTTP
request on a `QTimer`, i.e. the GUI thread, every five seconds. Commands now
queue to a single FIFO worker (order matters — two `next_turn`s must arrive as
pressed), and polling fetches on a worker and returns through a queued signal.

**Cross-thread hand-offs must be Qt signals, not `QTimer.singleShot()`.** A
timer created on a thread with no event loop never fires, and whatever it
scheduled is silently dropped. This ate every streamed snapshot once already.

**Never `print()`.** The packaged build runs `console=False`, so stdout is
discarded. Use the three tiers of reporting below.

**Foundry owns the round only while it has a live combat.** With Foundry closed
the bridge keeps serving its last snapshot (`active: false`, `round: 0`), so
`_apply_bridge_snapshot()` requires `combat["active"]` *and* `round >= 1`
before touching `round_counter`. `max(1, round_value)` silently rewound the
tracker to round 1 on every poll.

**Colours must be used by attribute access** — `colors.HP_LOW_ACTIVE`, never
`from ui.colors import HP_LOW_ACTIVE`. `colors.apply()` rebinds module globals,
and a name imported once binds to the old value forever.

**Read the version from `version.py` as text, not by importing it.** An import
can be served from a stale `__pycache__` entry: Python validates bytecode on
the source's mtime *in whole seconds* and its size, so changing the version to
another string of the same length within the same second is invisible to it.
This produced artifacts named after a version that did not exist.

**`CreatureTableModel._row_background()` is the single authority on a row's
colour.** It resolves the whole row before any per-cell tint, always returns a
colour for the active creature even when HP is untracked, and falls back to the
plain background last.

---

## Error reporting

Three tiers, by how much the user needs to care:

1. **`notify()` / `toast()`** — transient confirmations that dismiss
   themselves. The status-bar echo is opt-in; the toast always happens.
2. **`show_banner(key, ...)` / `clear_banner(key)`** — a persistent,
   non-blocking strip above the table for conditions that outlive a toast, like
   a lost bridge connection. Keyed, so re-showing updates in place instead of
   stacking.
3. **`report_error(parent, title, msg, exc)`** — a blocking modal with the
   traceback under *Show Details*, for when the thing the user asked for did
   not happen.

Uncaught exceptions reach a dialog through the excepthook installed in
`main.py`. `self._log(...)` infers severity from an `[ERROR]` / `[WARN]` /
`[DBG]` prefix.

---

## Testing

```bash
QT_QPA_PLATFORM=offscreen pipenv run python -m pytest tests/ -v
```

Offscreen, so no display is needed. The suite covers initiative ordering, the
bridge client and its command queue, the command-queue sweeper, snapshot
handling, the update installer and the launcher.

**When verifying row colours, sample painted pixels** from
`table.viewport().grab()`, not just `model.data(..., BackgroundRole)` — the
model can be right while the view paints something else. Sample above or below
the text baseline, or take the modal colour across the row; sampling mid-row
hits anti-aliased glyph pixels and gives false failures. Note that `_type` is a
hidden column of width 0, so `columnViewportPosition(0)` lands inside the name
column.

The update machinery has tests that use stand-in builds. The end-to-end check
that matters — two real packaged builds, install one, update to the other — is
manual, because stand-ins cannot exercise the locked-file behaviour that
motivates the whole design.
