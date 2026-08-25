# Updating the Windows build

The short version is still `git pull` then `./package_WIN.sh`, but four things
changed: the branch, a new required file, where the output lands, and the fact
that `.env` is no longer copied for you.

Everything below runs in **Git Bash**, from the repo root.

---

## 0. Push the branch first (on the Linux machine)

The new work is on `feat/distribution`, not `master`, and the last few commits
may still be local. From Linux:

```bash
git push origin feat/distribution
```

Nothing to pull otherwise.

## 1. Get the new code

```bash
git fetch origin
git checkout feat/distribution
git pull
```

This pulls ~44k lines, most of it the bundled SRD library under `srd_content/`
(333 monsters, 338 spells, 258 magic items). That directory is the payload the
build ships, so the pull has to succeed in full.

**If git refuses the checkout** complaining that an untracked file would be
overwritten — likely `images/d20_icon.ico` or something under `spells/` — that
is the `.gitignore` change landing: files that used to be ignored are now
tracked. Move your local copy aside and retry:

```bash
mv images/d20_icon.ico images/d20_icon.ico.local   # only if git complains
git checkout feat/distribution
```

## 2. Refresh dependencies

```bash
pipenv install
```

No new packages were added, so this is usually a no-op. Run it anyway — it is
cheap, and it fails loudly if the environment drifted.

## 3. Build

```bash
./package_WIN.sh
```

`pipenv run bash package_WIN.sh` still works, but is no longer needed: the
script finds pipenv itself and skips the wrapper when it is already inside the
environment.

New precondition: **`images/d20_icon.ico` must exist.** Windows PyInstaller
builds reject the `.png`, so the script now stops up front with a clear message
rather than failing halfway through. The `.ico` is committed, so a clean pull
has it; if you deleted yours, regenerate it with ImageMagick:

```bash
convert images/d20_icon.png -define icon:auto-resize=256,128,64,48,32,16 images/d20_icon.ico
```

Optional: `./package_WIN.sh --dev-install` also copies the repo's `.env` into
`%USERPROFILE%\.dnd_tracker_config\`. **This used to happen automatically and
now does not** — a release build must never carry your credentials. If you rely
on `.env` for bridge or storage settings, either pass the flag or move those
values into Settings (see step 5), which is where they belong now.

## 4. Install the result

The output moved. You now get a versioned zip:

```text
dist/combat-tracker-0.1.0-windows-x64.zip
```

with the staged tree beside it at
`package_win/combat-tracker-0.1.0-windows-x64/`.

Extract the zip **somewhere outside the repo** — `Documents\combat-tracker\`,
say — and run:

```text
combat_tracker\combat_tracker.exe
```

Do not run it from `dist/`, `build/` or `package_win/`: every build starts by
deleting all three, which would take your installed copy with it.

Windows SmartScreen will warn about an unrecognized publisher — the build is
not code-signed. "More info" → "Run anyway".

To upgrade an existing install, delete the old `combat_tracker\` folder and
extract the new one in its place. Your data is not in there (see below), so
nothing is lost.

## 5. First launch after the upgrade

Your settings and data live in `%USERPROFILE%\.dnd_tracker_config\` and survive
reinstalls untouched.

Two things are worth doing once, both under **File → Settings…**, which is now
tabbed:

- **Content** — installs the bundled SRD monsters, spells and magic items into
  your library. Re-running only adds what is missing; it never overwrites your
  own edits. The magic items are what the Shop Generator's Magic Shop and
  Apothecary profiles draw on, so install them before expecting those to fill.
- **Foundry VTT** — the bridge is **off by default** now and lives here rather
  than in `.env`. Changes apply immediately, no restart. Remember that Foundry
  module settings are world-scoped: a new world means re-entering the bridge URL
  and secret on the Foundry side.
- **Updates** — an optional startup check against GitHub releases that raises a
  banner when a newer version exists. It only tells you; it never downloads
  anything. Turn it off here or with `UPDATE_CHECK_ENABLED=0`.

**Help → Release Notes** shows the changelog for the build you are actually
running, offline.

## 6. Testing a clean first run

To see exactly what a new user sees without touching your real settings, logs
or data, point the config directory somewhere disposable:

```bash
DND_TRACKER_CONFIG_DIR=/c/temp/profile pipenv run python main.py
```

Delete that directory to reset.

---

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `images/d20_icon.ico is missing` | See step 3. |
| `PyInstaller is not installed in this environment` | `pipenv install` (step 2). |
| `Neither zip nor powershell.exe found` | Git Bash has no `zip(1)`; the script falls back to PowerShell. If both are missing the staged tree is still left in `package_win/` and can be zipped by hand. |
| App starts with the setup wizard again | No `settings.json` in `%USERPROFILE%\.dnd_tracker_config\` yet — expected if this is your first build with the settings system. Fill it in once. |
| Magic Shop generates empty shelves | Install the magic items from Settings → Content. |
| General Store / Blacksmith / Trade Post still sparse | Expected: the SRD ships magic items only, so `adventuring_gear`, `tool` and `trade_good` slots match nothing until you add mundane items yourself. |
