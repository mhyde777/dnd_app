# D&D 5e Combat Tracker

A desktop app for running combat in D&D 5e: initiative, hit points, conditions,
death saves and combat state, with optional two-way sync to Foundry VTT.

Built for use at an actual table — the things you do every turn are one click
or one key, and the things you do once are behind a menu.

![Python 3.10](https://img.shields.io/badge/python-3.10-blue)

---

## Get it running

**Just want to use it:** download one file from the
[latest release](https://github.com/mhyde777/dnd_app/releases/latest) and open
it. There is nothing to unpack and nothing to configure.

| | | |
|---|---|---|
| **Windows** | `combat-tracker-…-x64-setup.exe` | Run it. Installs for you only, so it never asks for an administrator password. |
| **Linux** | `combat-tracker-…-x86_64.AppImage` | Right-click → *Properties* → tick **Allow executing file as program**, then double-click. |
| **macOS** | — | No build yet. See [docs/packaging-macos.md](docs/packaging-macos.md). |

<details>
<summary><b>Windows warns "unrecognized publisher"</b> — what that means</summary>

The installer is not code-signed, so SmartScreen shows a blue warning on first
run: click **More info**, then **Run anyway**.

The warning means Microsoft has not seen this file often enough to vouch for
it, not that anything is wrong with it. If you would rather check for yourself,
every release publishes a `SHA256SUMS` file; in PowerShell:

```powershell
Get-FileHash .\combat-tracker-0.6.0-x64-setup.exe -Algorithm SHA256
```

and compare it with the line for that filename in `SHA256SUMS`.
</details>

<details>
<summary><b>Linux: the AppImage offers to install itself</b> — why, and what it does</summary>

An AppImage is a single read-only file, which is what makes it easy to
download but also means it cannot update itself. So the first time you run it,
it offers to install into `~/.local/opt/combat-tracker` and add itself to your
applications menu — after which **Help → Check for Updates** installs new
versions for you.

Answering "Not now" is fine; it keeps working from wherever you put it, and
**File → Install Combat Tracker…** is there if you change your mind. Nothing
outside your home directory is written either way.
</details>

On first launch you choose where to keep your data and whether to install the
bundled SRD library. Both are changeable later.

Also on every release, for anyone who wants them: a `.tar.gz` and a `.zip` of
the same build. These are what **Help → Check for Updates** downloads, and they
are the right choice for a portable install or one you want to place yourself.

> **Updating from a version before 0.2.1?** The install layout changed to make
> in-app updates possible, and it cannot install itself into existence — run
> this release's installer or AppImage once, and updates after that are a
> single button. Nothing in `~/.dnd_tracker_config/` is affected.

---

## Documentation

**All of this is in the app**, under **Help → Documentation** (`Shift+F1`) — a
window you can leave open beside the tracker while you work. It ships with the
build, so it works offline and describes the version you are actually running.

| | |
|---|---|
| **[Installing](docs/installing.md)** | Getting it onto Windows or Linux, and uninstalling |
| **[Running a combat](docs/using-the-tracker.md)** | Everything the app does, in the order you meet it |
| **[Where your data lives](docs/storage.md)** | Storage providers — a folder, Dropbox, WebDAV, S3 — backups, syncing settings |
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

### Cutting a release

Pushing a `v*` tag is the whole process. `.github/workflows/release.yml` builds
both platforms in parallel and publishes one complete release:

```bash
./release.sh patch --dry-run   # say what it would do
./release.sh patch             # 0.4.1 -> 0.4.2
./release.sh minor             # 0.4.1 -> 0.5.0
```

It refuses to start from a dirty tree, the wrong branch, a tag that already
exists, an empty changelog, or failing tests — everything after that point is
public, and stopping is cheapest before any of it has happened.

The release is created as a **draft**, uploaded, and only then published, so it
never appears publicly with its assets missing. CI then re-reads the release
from the API and fails if any expected artifact is absent. Building both
platforms from one tag is the point: PyInstaller cannot cross-compile, and when
this was two manual builds a release could — and did — go out with no Windows
assets, leaving every Windows user's updater reporting "no build for this
system".

Each release carries, per platform, an installer for people and an archive for
the in-app updater:

| Artifact | For |
|---|---|
| `…-x64-setup.exe` | Windows, first install ([Inno Setup](installer/windows/combat-tracker.iss)) |
| `…-x86_64.AppImage` | Linux, first install ([build script](installer/linux/build_appimage.sh)) |
| `…-windows-x64.zip`, `…-linux-x86_64.tar.gz` | Help → Check for Updates |
| `foundryvtt-bridge.zip`, `module.json` | the Foundry module |
| `SHA256SUMS` | every artifact above |

#### Building locally

Needed for testing a build, or to publish by hand when CI is unavailable:

```bash
./package.sh                    # Linux   -> .tar.gz + .AppImage + SHA256SUMS
./package_WIN.sh                # Windows (Git Bash) -> .zip + setup.exe
./package_module.sh             # the Foundry module
./package.sh --dev-install      # also install to ~/.local/opt for daily use
./package_WIN.sh --dev-install  # same, to %LOCALAPPDATA%\Programs + a Start Menu shortcut
./release.sh patch --local      # publish from here instead of CI
```

The Linux build needs `squashfs-tools` for the AppImage; the Windows build
needs [Inno Setup](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`) for the installer. Both scripts warn
and carry on without them, producing the archive alone.

`--publish` and `--local` need the [GitHub CLI](https://cli.github.com/)
(`gh auth login`) and the tag pushed.

The Windows installer is unsigned. `installer/windows/combat-tracker.iss` is
wired for signing already — passing `/DSign` to `ISCC` turns it on — so adding
a certificate later is a flag, not a restructuring.

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
