# Changelog

What changed in each release, in enough detail to decide whether you want it.

Nothing here updates itself. If the version you have works for you, keep it —
see [Running an older version](#running-an-older-version) below.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/): given `MAJOR.MINOR.PATCH`,
a MAJOR bump is the only kind that can require you to change how you work.

---

## [Unreleased]

### Added

- **Help → Installed Versions** switches between the versions installed side by
  side and removes ones you no longer want. Updating keeps the previous build
  rather than replacing it, so going back is the same operation as going
  forward. The running version and the one queued to start next can't be
  deleted.
- Versions that are no longer on disk are still listed, from a history kept in
  settings, and can be downloaded again from their release — so going back
  isn't limited to what is stored locally.
- Old versions are removed when a new one **starts successfully**, rather than
  when it is installed, so a failed update still has the previous build to fall
  back to. `keep_versions` (default 2) sets how many are kept.
- A superseded version then gets an hour's reprieve before it is deleted
  (`version_grace_minutes`, default 60), so a build that starts cleanly and
  only then turns out to be wrong is still there to go back to instantly. The
  Installed Versions dialog counts it down, and choosing that version again
  cancels its retirement.

### Fixed

- Pruning old versions could delete the one `current` pointed at — its
  docstring said it protected that, but it only protected the *running*
  version. Those differ exactly when you have reverted to an older build, which
  is when losing it would matter most.


## [0.3.0] — 2026-08-26

### Added

- `./package.sh --publish` (and `--publish` on the Windows script) builds and
  uploads the artifacts to the GitHub release in one step, then asks the API
  what is actually attached. Publishing a release with no files on it looks
  finished but leaves the in-app updater reporting "no build for this system",
  which reads like a bug in the app rather than a missing upload.

- **View → Status Bar Messages** turns the bottom-left text on and off, and is
  off by default. The turn announcement fired on every turn change and repeated
  what the "Active:" label and the highlighted row already say. Toasts are
  unaffected — anything worth interrupting for still raises one.

- **Changes that need a restart now offer one.** Saving a storage change asks
  "Restart now?" and does it — saving your combat first — instead of telling
  you to close the dialog, close the app and start it again yourself. Declining
  leaves a banner with the same button, so the offer stays one click away.

### Fixed

- Settings showed "restart the app for storage changes to take effect" every
  time it was saved, whether or not anything had changed and whether or not a
  restart was needed.

- **The round counter no longer rewinds to 1 while Foundry is closed.** The
  bridge keeps serving its last snapshot — combat inactive, `round: 0` — and
  the app took that as gospel on every poll. Foundry is only authoritative
  about the round while it actually has a combat running.
- **Polling the bridge no longer freezes the window.** The poll timer ran the
  HTTP request inline on the UI thread, so the app locked up for a round trip
  every five seconds (~420ms against a remote bridge). It runs on a worker now
  and arrives through the same queued signal the streaming path uses; a bridge
  slower than the interval is skipped rather than stacking up threads.
- **Advancing a turn is no longer sluggish.** Every command sent to the Foundry
  bridge was POSTed on the UI thread, so pressing Next waited on a round trip
  before the table repainted — ~460ms against a remote bridge, which was the
  whole of the delay. Commands are queued and delivered on a worker thread now,
  in the order they were sent: 383ms down to 3ms. Anything still in flight is
  given a moment to go out when the app closes.
- Bridge logging went to `print()`, which the packaged build discards entirely
  (`console=False`). It goes to the app log now — which matters more with
  delivery on a worker thread, where a failure has no other way to surface.

- The packaging scripts could stamp a build with the wrong version. They read
  `__version__` by importing it, and an import can be served from a stale
  `__pycache__` entry — Python validates bytecode against the source's
  mtime-in-whole-seconds and size, so editing the version to another string of
  the same length within the same second is invisible to it. They read the file
  as text now.


## [0.2.1] — 2026-08-26

### Added

- **Update from inside the app.** The banner's "Get <version>" button opens a
  dialog with the release notes and one button that downloads the build, checks
  it against its published checksum, installs it and restarts into it.
- **Help → Check for Updates** asks on demand, instead of the check only
  running once at startup. It answers either way, including "you are on the
  latest version".
- Updates install *alongside* the running version rather than over it, so the
  previous version stays on disk and remains runnable. If a new version fails
  to start, the launcher notices and falls back to it automatically. See
  `docs/auto-update.md`.

### Changed

- **The install layout has changed**, which is what makes updating possible: a
  `combat-tracker` launcher at the top, the build under `versions/<version>/`,
  and a `current` file naming which to run. Shortcuts point at the launcher.

  **Existing installs need to be replaced once.** Unpack this release
  somewhere and run `install.sh` (Linux) or make a shortcut to
  `combat-tracker.exe` (Windows); updates after that are a single button. The
  app detects an older-style install and says so instead of offering a button
  that cannot work. Nothing in `~/.dnd_tracker_config` is affected.
- Release builds now publish a `SHA256SUMS` file alongside the artifact.

### Fixed

- The update banner's only button was "What's New?"; the helper that would have
  opened the releases page was written but never connected to anything, so
  there was no way to get to the download from inside the app.

## [0.2.0] — 2026-08-26

### Added

- **Damage and heal from the initiative table.** Selecting rows in the table
  picks the same targets as the combatant list — the two mirror each other — so
  you no longer have to find a creature a second time in a different widget to
  apply damage to it.
- **Clicking an HP cell opens a damage/heal box** for that one creature, with
  the amount field already focused: Enter damages, Shift+Enter heals. Temp HP
  and Max HP Bonus are still there, below a separator.
- **Shift+click takes a run of combatants** in the list. Plain clicks still add
  and remove one at a time, which is what picking scattered creatures needs.
- **Keyboard shortcuts are rebindable** — View → Customize Shortcuts. Only the
  keys you change are stored, so later defaults still reach you, and two
  commands cannot be given the same key (Qt would fire neither). Help →
  Keyboard Shortcuts lists whatever is currently bound.
- **The Combat Controls panel can be rearranged** — View → Customize Combat
  Controls hides and reorders its sections. Nothing becomes unreachable: HP
  mods are on each creature's HP cell, and the table selects the same targets
  as the combatant list.
- **Settings can travel between machines** — Settings → Sync pushes and pulls
  your layout, colours, shortcuts and toolbar through whichever storage you
  already use. Credentials, the Foundry secret, your data directory and window
  geometry deliberately stay on the machine they were set on, and a pull merges
  rather than replaces, so it can never cost you your API key.
- **258 SRD magic items** join the bundled library, with rarity, type,
  attunement and full descriptions. Install them from Settings → Content
  alongside the monsters and spells. This is what the Magic Shop and Apothecary
  profiles were always meant to draw on — every rarity-based slot in them
  previously matched zero items, because the library held only mundane gear.

### Fixed

- **Statblock zoom resizes the text.** It scaled the document's base font, but
  every size in a statblock is an explicit pixel size in the HTML, which wins —
  so the line spacing grew and not one letter changed size.
- **No more blank strip under the last row.** After removing a combatant the
  table kept a horizontal scrollbar's worth of height it no longer needed,
  because Qt reports scrollbar visibility a layout pass behind.
- **The combatant selection survives applying damage.** Rebuilding the list
  dropped it, and that rebuild runs after every HP change — so hitting the same
  group twice meant picking it again first.
- **The monster picker fits the monsters in the fight** instead of sitting at a
  fixed height with empty space below, taking room from the statblock.

- **The Shop Generator's "Send to Foundry" button works.** It called a method
  that does not exist on the bridge client, so it failed with an
  AttributeError every time. The Foundry module had been handling the
  `create_journal` command all along — only the app-side call was missing.
  The button is now hidden entirely when no Foundry bridge is configured.
- **The Shop Generator no longer locks the window for half a minute.** It
  fetched every item in the library one HTTP request at a time, on the UI
  thread — and did it again on every Generate click. Fetching concurrently and
  caching the result took a 505-item library from ~21s per click to ~2.8s on
  open and effectively nothing thereafter. Reopen the dialog to pick up newly
  added items.
- **Foundry streaming (SSE) mode now works.** Snapshots arrived on the reader
  thread and were handed to the UI with a timer created in a thread that has
  no event loop, so it never fired and every streamed update was silently
  discarded. It is a queued signal now.
- **The stream no longer reconnects every few seconds.** The single-request
  timeout was being applied to the long-lived stream, so an idle connection
  expired and reconnected in a loop -- polling, but worse. Connect keeps the
  short timeout; the read uses `BRIDGE_STREAM_READ_TIMEOUT` (65s).

### Changed

- **Characters and PC Groups have their own menu**, with Initialize Players,
  rather than sitting under File — none of the three is a file operation. The
  Customize entries that appeared in both File and View are now only in View,
  alongside the other customizers.

- **Switching Foundry transport no longer needs a restart.** Saving settings
  swaps between streaming and polling live, turns sync off, and picks up a
  changed bridge URL or secret. Storage changes still need a relaunch, and now
  say so in a banner instead of appearing to do nothing.
- **Settings is tabbed** — Storage, Foundry VTT, Content and Updates — instead
  of one long scroll. Storage is first because it is the only tab that has to
  be answered; everything else has a working default.
- **Foundry sync is configured in the app, not a dotfile.** File → Settings has
  a single "Sync with Foundry VTT" switch; the bridge URL, shared secret and
  transport options stay hidden until it is on, so anyone not using Foundry
  never sees them. Existing `.env` files still work and are never written to.
- `settings.json` is now written 0600. It holds the storage API key and the
  Foundry secret, and was previously group- and world-readable.
- The update-notification toggle is now in the UI (Updates tab) rather than
  only an environment variable.
- Removed two `load_dotenv()` calls that searched upward from the working
  directory, so a packaged app could absorb an unrelated `.env` from wherever
  its launcher happened to start it.

## [0.1.0] — 2026-08-24

First release intended for anyone other than its author.

### Added

- **SRD 5.2.1 content, bundled.** 333 monster stat blocks and 338 spells ship
  with the app, so a fresh install has a usable library instead of an empty
  one. Verified against the SRD's own Index of Stat Blocks: 330 indexed
  creatures, 330 extracted. Used under CC-BY-4.0; see `LICENSE-SRD.md`.
- **Setup wizard installs that content** into whichever storage you choose,
  local files or your own API server, with per-category counts and a working
  Cancel. Re-running only adds what is missing, so your own edits to an entry
  are never overwritten.
- **Help → About** with version, bundled counts and the SRD attribution.
- **Update notifications.** The app checks for a newer release on startup and
  shows a dismissible banner. It never downloads or installs anything — you
  decide. Turn it off entirely with `UPDATE_CHECK_ENABLED=0` or the
  `update_check_enabled` setting.
- **`DND_TRACKER_CONFIG_DIR`** redirects settings, logs and data to a
  throwaway directory, so you can try a version without touching your real
  profile:
  `DND_TRACKER_CONFIG_DIR=/tmp/try-it ./combat_tracker/combat_tracker`
- Documentation for the content parsers (`docs/importing-content.md`), the
  Foundry bridge (`docs/foundry-bridge.md`), and what a macOS build would
  still need (`docs/packaging-macos.md`).

### Changed

- **The Foundry bridge is off by default.** It used to start a local server on
  port 8787 and invent an access token on every launch, whether or not you use
  Foundry. Existing `.env` setups are unaffected — see `docs/foundry-bridge.md`
  to turn it on.
- **Panels keep the width you gave them.** They used to drift a little every
  session, because a growing window handed its extra width to the panels
  rather than the table, and the window manager's maximize is such a growth.
- The app now opens maximized every time. Un-maximizing returns it to your
  saved size.
- Release builds write nothing outside the repository. Installing a desktop
  launcher and copying a developer `.env` moved behind `package.sh --dev-install`.

### Fixed

- **Spell descriptions were being discarded.** A description whose opening
  clause ended in a colon — "You touch a creature and remove one of the
  following effects from it: …" — was mistaken for an unrecognised property
  header and dropped entirely. This affected 183 of the 338 SRD spells, and
  any spell you pasted in yourself that was worded that way.
- **Windows builds were missing a dependency fix.** The workaround for
  `charset_normalizer` matched only `.so`, and the file is named `.pyd` on
  Windows, so the bug it was written for silently returned there.
- **Windows builds failed on the icon.** PyInstaller was handed a `.png`;
  Windows requires `.ico` and macOS `.icns`.
- Settings are no longer destroyed by the settings dialog. Saving from
  **File → Settings** wrote only the storage keys over the whole file, wiping
  panel layout, toolbar, colours, active PC group and bridge configuration.
- The bulk spell importer is now actually in the repository. A `.gitignore`
  rule had been hiding it, so the script the README told you to run was never
  in a clone.

### Removed

- **Hide/Reveal from Player View** in the combatant right-click menu. It
  toggled a flag nothing has read since the Player View was abandoned.
- Player View documentation, for a feature that does not exist in the code.

### Known issues

- No macOS build. See `docs/packaging-macos.md`.
- Windows builds are unsigned, so SmartScreen will warn on first run.

---

## Running an older version

Releases are independent. Each unpacks into its own directory and none of them
delete or upgrade another, so you can keep as many as you like side by side and
switch by pointing your launcher at a different one.

**Your data is shared between them**, which is what makes switching painless —
and carries one caveat worth understanding:

> An older version will happily **read** newer save files; it ignores fields it
> does not recognise. But when it **saves**, it writes only the fields it knows
> about, so anything a newer version added is dropped from that file.

In practice: moving down a version and staying there is fine. Bouncing between
versions while editing the same encounter can quietly lose whatever the newer
one added. If you are testing a new release, point it at a throwaway profile
with `DND_TRACKER_CONFIG_DIR` and your real data cannot be touched at all.

[Unreleased]: https://github.com/mhyde777/dnd_app/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mhyde777/dnd_app/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/mhyde777/dnd_app/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/mhyde777/dnd_app/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mhyde777/dnd_app/releases/tag/v0.1.0
