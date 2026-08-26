# D&D 5e Combat Tracker

A desktop app for running combat in D&D 5e: initiative, hit points, conditions,
death saves and combat state, with optional two-way sync to Foundry VTT.

Built for use at an actual table — the things you do every turn are one click
or one key, and the things you do once are behind a menu.

![Python 3.10](https://img.shields.io/badge/python-3.10-blue)

---

## Get it running

**Just want to use it:** download the build for your system from the
[latest release](https://github.com/mhyde777/dnd_app/releases/latest),
unpack it somewhere permanent, and run it.

| | |
|---|---|
| **Linux** | `tar -xzf combat-tracker-*-linux-*.tar.gz`, then `./combat-tracker`. Run `./install.sh` for a desktop entry. |
| **Windows** | Unzip, then `combat-tracker.exe`. The build is unsigned, so SmartScreen warns on first run — *More info* → *Run anyway*. |
| **macOS** | No build yet. See [docs/packaging-macos.md](docs/packaging-macos.md). |

Run `combat-tracker`, **not** the binary inside `versions/`. That one is the
launcher, and it is what makes in-app updates work.

On first launch you choose where to keep your data and whether to install the
bundled SRD library. Both are changeable later.

> **Updating from a version before 0.2.1?** The install layout changed to make
> in-app updates possible, and it cannot install itself into existence — unpack
> this release once, and updates after that are a single button. Nothing in
> `~/.dnd_tracker_config/` is affected.

---

## Documentation

| | |
|---|---|
| **[Running a combat](docs/using-the-tracker.md)** | Everything the app does, in the order you meet it |
| **[Where your data lives](docs/storage.md)** | Local folder or shared API, backups, syncing settings |
| **[Connecting to Foundry VTT](docs/foundry-setup.md)** | The bridge, the module, and what to do when it doesn't work |
| **[Importing content](docs/importing-content.md)** | Statblocks, spells and items from D&D Beyond |
| **[In-app updating](docs/auto-update.md)** | How updates install, and how to go back |
| **[Changelog](CHANGELOG.md)** | What changed in each release |

---

## What it does

- **Initiative** — sorted automatically, natural ordering so "Goblin 2" comes
  before "Goblin 10". Lair actions get their own place in the order.
- **HP** — click a creature's HP to damage or heal it, or select several and
  do them together. Temp HP, max HP bonuses, and a concentration prompt with
  the DC already worked out.
- **Conditions and the action economy** — conditions per creature, action /
  bonus / reaction tracking that resets each round, death saves for players
  at 0 HP.
- **Encounters** — build them ahead of time, load them, or merge one into a
  fight in progress for reinforcements.
- **SRD content included** — 333 monsters, 338 spells, 258 magic items, with
  search. Import your own from D&D Beyond text.
- **Foundry VTT sync** — optional, two-way, and off unless you turn it on.
- **Yours to arrange** — panels, toolbar, colours and keyboard shortcuts are
  all configurable, and settings can travel between machines.

---

## Running from source

Python 3.10.

```bash
pipenv install
pipenv run python main.py
```

Or with pip:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Tests (offscreen, so they need no display):

```bash
QT_QPA_PLATFORM=offscreen pipenv run python -m pytest tests/ -v
```

### Building a release

PyInstaller cannot cross-compile, so each platform builds on that platform.

```bash
./package.sh                  # Linux  -> dist/*.tar.gz + SHA256SUMS
./package_WIN.sh              # Windows (Git Bash) -> dist/*.zip
./package_module.sh           # the Foundry module -> dist/foundryvtt-bridge.zip
./package.sh --dev-install    # also install to ~/.local/opt for daily use
./package.sh --publish        # also upload to the GitHub release for this version
```

`--publish` needs the [GitHub CLI](https://cli.github.com/) (`gh auth login`)
and the tag pushed. It uploads the artifacts and then asks the API what is
actually attached, because a release published with no files on it looks
exactly like a finished one.

Repository layout, how the pieces fit together, and the invariants worth
knowing before changing things are in
[docs/architecture.md](docs/architecture.md).

---

## How this was built

This app was built with substantial help from AI coding assistants, which wrote or reworked a large share of the code. This work was directed, reviewed and tested by Mason Hyde, and the decisions about what this should be and how it should behave at the table are mine. But it would be misleading to present the result as though I had typed it all, and I would rather say so plainly than let anyone assume otherwise.

Early versions of the app and the code foundations were implemented by Mason and Mikhail Hyde. 

The same notice is in Help → About, because someone running the packaged app
has no reason to read this file.

---

## Licence and attribution

The bundled reference content is from the **System Reference Document 5.2.1**,
© Wizards of the Coast LLC, used under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode). See
[LICENSE-SRD.md](LICENSE-SRD.md); the attribution also travels with the app in
Help → About.

This project is not affiliated with or endorsed by Wizards of the Coast or
Foundry Gaming LLC.
