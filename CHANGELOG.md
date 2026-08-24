# Changelog

What changed in each release, in enough detail to decide whether you want it.

Nothing here updates itself. If the version you have works for you, keep it —
see [Running an older version](#running-an-older-version) below.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/): given `MAJOR.MINOR.PATCH`,
a MAJOR bump is the only kind that can require you to change how you work.

---

## [Unreleased]

### Fixed

- **Foundry streaming (SSE) mode now works.** Snapshots arrived on the reader
  thread and were handed to the UI with a timer created in a thread that has
  no event loop, so it never fired and every streamed update was silently
  discarded. It is a queued signal now.
- **The stream no longer reconnects every few seconds.** The single-request
  timeout was being applied to the long-lived stream, so an idle connection
  expired and reconnected in a loop -- polling, but worse. Connect keeps the
  short timeout; the read uses `BRIDGE_STREAM_READ_TIMEOUT` (65s).

### Changed

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

[Unreleased]: https://github.com/mhyde777/dnd_app/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mhyde777/dnd_app/releases/tag/v0.1.0
