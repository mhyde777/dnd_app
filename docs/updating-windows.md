# Installing and updating on Windows

PyInstaller cannot cross-compile, so a Windows build has to be made on the
Windows machine. Everything below runs in **Git Bash**, from the repo root.

Once you are on 0.4.2 or newer this is a one-time exercise: after the first
install, **Help → Check for Updates** does the rest, the same as on Linux. See
[auto-update.md](auto-update.md) for what that button actually does.

---

## 1. Get the code

The work is on `master`.

```bash
git fetch origin
git checkout master
git pull
```

> **If you are coming from `feat/distribution`:** that branch is frozen at
> **0.1.0**. An earlier version of this document told you to check it out, so a
> `git pull` there reports "already up to date" and rebuilds 0.1.0 forever.
> Checking out `master` is the fix. Confirm with:
>
> ```bash
> sed -n 's/^__version__ = "\(.*\)"/\1/p' lib/app/version.py
> ```

**If git refuses the checkout** complaining that an untracked file would be
overwritten — likely `images/d20_icon.ico` — that is a `.gitignore` change
landing: files that used to be ignored are now tracked. Move your copy aside
and retry:

```bash
mv images/d20_icon.ico images/d20_icon.ico.local
git checkout master
```

## 2. Refresh dependencies

```bash
pipenv install
```

Usually a no-op, but it is cheap and fails loudly if the environment drifted.

## 3. Build and install

```bash
./package_WIN.sh --dev-install
```

`--dev-install` installs the build for daily use, the same way `./package.sh
--dev-install` does on Linux. It:

- installs the versioned tree into `%LOCALAPPDATA%\Programs\combat-tracker\`,
- writes a **Combat Tracker** shortcut into your Start Menu pointing at the
  launcher,
- copies the repo's `.env` into `%USERPROFILE%\.dnd_tracker_config\`, if you
  have one.

Set `DEV_INSTALL_DIR` to install somewhere else.

Only *this version's* directory under `versions\` is replaced — versions
installed by an earlier update are left alone, since they are the rollback.

**Close the app first.** Windows holds a running `.exe` and its loaded DLLs
open, so installing over a live copy would fail partway through. The script
checks before building and stops with a message rather than wasting the build.

Without the flag you get a release zip and nothing else:

```text
dist/combat-tracker-<version>-windows-x64.zip
```

staged beside it at `package_win/combat-tracker-<version>-windows-x64/`. To
install that by hand, extract it **somewhere outside the repo** — every build
starts by deleting `build/`, `dist/` and `package_win/`, which would take an
installed copy with it.

Two preconditions the script enforces up front:

- **`images/d20_icon.ico` must exist.** Windows PyInstaller builds reject the
  `.png`. The `.ico` is committed, so a clean pull has it; regenerate a deleted
  one with `convert images/d20_icon.png -define
  icon:auto-resize=256,128,64,48,32,16 images/d20_icon.ico`.
- **PyInstaller must be installed** in the pipenv environment.

## 4. Run it

Start it from the Start Menu, or:

```text
%LOCALAPPDATA%\Programs\combat-tracker\combat-tracker.exe
```

Run **`combat-tracker.exe` at the root**, never the `combat_tracker.exe` under
`versions\`. The root binary is the launcher: it reads `current` to decide
which version to start, and it is what lets Help → Check for Updates install a
new version and restart into it. The inner one runs, but that copy cannot
update itself.

Windows SmartScreen will warn about an unrecognized publisher — the build is
not code-signed. *More info* → *Run anyway*.

Upgrading from a **0.1.0-era install** — the flat
`combat_tracker\combat_tracker.exe` layout with no launcher — means deleting
that old folder and any shortcut to it. Nothing is lost: your data lives in
`%USERPROFILE%\.dnd_tracker_config\` and survives reinstalls untouched.

## 5. Updating from then on

**Help → Check for Updates** downloads the release, verifies its checksum,
installs it beside the running version and restarts into it. There is also an
optional startup check under **File → Settings… → Updates** that raises a
banner when a newer version exists; it only tells you, it never downloads.

This works only if the release carries a Windows asset. The updater looks for

```text
combat-tracker-<version>-windows-x64.zip
```

and reports "no build for this system" when the release has only the Linux
tarball — which is exactly what a release cut on the Linux machine produces.
So publishing a version is two machines: cut and publish on Linux, then from
Windows, on the same tag:

```bash
./package_WIN.sh --publish
```

That builds the Windows zip and attaches it to the existing GitHub release,
then verifies it landed. Needs `gh` installed and logged in
(`winget install GitHub.cli`, `gh auth login`).

## 6. First launch after an upgrade

Your settings and data live in `%USERPROFILE%\.dnd_tracker_config\`. Worth a
look under **File → Settings…**:

- **Content** — installs the bundled SRD monsters, spells and magic items into
  your library. Re-running only adds what is missing; it never overwrites your
  own edits. The magic items are what the Shop Generator's Magic Shop and
  Apothecary profiles draw on.
- **Foundry VTT** — the bridge is off by default. Changes apply immediately, no
  restart. Foundry module settings are world-scoped: a new world means
  re-entering the bridge URL and secret on the Foundry side.
- **Updates** — the startup check described above. Turn it off here or with
  `UPDATE_CHECK_ENABLED=0`.

**Help → Release Notes** shows the changelog for the build you are running,
offline.

## 7. Testing a clean first run

To see what a new user sees without touching your real settings, logs or data,
point the config directory somewhere disposable:

```bash
DND_TRACKER_CONFIG_DIR=/c/temp/profile pipenv run python main.py
```

Delete that directory to reset.

---

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Built app is an old version | Wrong branch — see step 1. Check `lib/app/version.py`. |
| `Combat Tracker is running -- close it before --dev-install` | Close the app; Windows locks the running `.exe` and its DLLs. |
| `images/d20_icon.ico is missing` | See step 3. |
| `PyInstaller is not installed in this environment` | `pipenv install` (step 2). |
| `Neither zip nor powershell.exe found` | Git Bash has no `zip(1)`; the script falls back to PowerShell. With both missing the staged tree is still in `package_win/` and can be zipped by hand. |
| `warning: could not create the Start Menu shortcut` | Non-fatal; the install is fine, make your own shortcut to `combat-tracker.exe`. |
| Check for Updates says "no build for this system" | The release has no Windows zip — see step 5. |
| Update dialog offers only "Download", not "Update and Restart" | It says why: a source checkout, a pre-launcher install, a missing launcher, or an install directory you cannot write to. Usually it means you started the inner `versions\...\combat_tracker.exe` instead of the root `combat-tracker.exe`. |
| App starts with the setup wizard again | No `settings.json` in `%USERPROFILE%\.dnd_tracker_config\` yet. Fill it in once. |
| Magic Shop generates empty shelves | Install the magic items from Settings → Content. |
| General Store / Blacksmith / Trade Post still sparse | Expected: the SRD ships magic items only, so `adventuring_gear`, `tool` and `trade_good` slots match nothing until you add mundane items yourself. |
