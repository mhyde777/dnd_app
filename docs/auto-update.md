# In-app updating

One button in the update dialog downloads a release, checks it, installs it and
restarts into it. This describes how, what happens when a step fails, and what
is deliberately still missing.

## The layout

```
<root>/
    combat-tracker[.exe]     the launcher — what shortcuts point at
    versions/
        0.2.0/               a whole PyInstaller one-folder build
            combat_tracker[.exe]
            _internal/
        0.3.0/               an update, installed alongside
    current                  text file naming the version to run
    launching                written before a start, cleared once a window is up
    launcher.log             why the launcher did what it did
```

**Nothing is ever written over.** An update adds a directory under `versions/`
and repoints `current`. That single decision is what makes updating a running
app possible: on Windows a running `.exe` and its loaded DLLs are held open and
cannot be replaced, and on every platform a PyInstaller folder loads files
lazily, so overwriting one underneath a live process is a crash waiting to
happen. Adding a sibling directory touches nothing that is open.

It is also the rollback. The previous version is still on disk and still
runnable; going back is one line in `current`.

## What happens when you press the button

1. **Download** the asset matching this platform and architecture, streamed to
   `versions/.downloads/` with progress and a working Cancel. It writes to a
   `.part` file renamed only on success, so an interrupted download never
   leaves something that looks like a usable build.
2. **Verify** against the release's `digest` field, or a `SHA256SUMS` asset
   published alongside. A mismatch deletes the file and stops. With neither
   published the dialog says verification was skipped rather than implying a
   check happened — TLS to github.com is doing the real work there.
3. **Extract** to `versions/<new>.incoming`, refusing any archive member that
   would write outside it: an absolute path, a `..`, or a symlink pointing out.
4. **Install** by renaming `.incoming` to `versions/<new>` — but only after the
   app binary has been found inside it. A rename within one directory is as
   close to atomic as this gets, and it means the launcher can never catch a
   half-written version, because a half-written one is not yet called by its
   version name.
5. **Repoint** `current` (written to a temp file and renamed, for the same
   reason) and prune to the newest three, never removing the running version.
6. **Restart**: save state, start the launcher with `--wait-pid <our pid>`, and
   quit. The launcher waits for the old process to exit before starting the new
   one, so the two never overlap — otherwise both would hold the log open and
   both would write settings on close, and whichever quit *second* would win.

## When a new version won't start

The launcher writes `launching` naming the version it is about to run, and the
app deletes it once a window is up (`main.py`). A `launching` file still there
on the next start means that build failed before it could clear it, so the
launcher skips it, falls back to the previous version, repairs `current`, and
notes it in `launcher.log`.

Without this a bad build relaunches itself forever and the only fix is a file
manager. It is the difference between one-click update and one-click brick.

The check is "did it get a window up", not "did it exit cleanly" — a build that
starts and then crashes an hour later is not an update problem.

## Where it degrades

`install_layout.can_self_update()` decides, and the dialog explains rather than
disabling a button with no reason:

- **A source checkout** — update it with git.
- **An install predating this layout** — a flat folder with no launcher.
  Download this release and unpack it once; updates after that are one button.
- **No write permission to the install root** — install somewhere you own.
- **No asset for this platform** in the release.

In the first three the button still downloads the build to Downloads.

## Still missing

- **Code signing.** The builds are unsigned, so Windows SmartScreen warns on
  every one. An updater that fetches and runs new code makes that matter more
  than it did when a user consciously downloaded a file. A certificate is
  roughly $100–400/year.
- **Reverting from inside the app.** The previous version is on disk and the
  launcher will fall back to it automatically if the new one fails to start,
  but there is no "go back to 0.2.0" menu item for a version that starts and is
  merely worse. Editing `current` does it.
- **Delta updates.** Every update is the whole ~60MB build.
- **macOS.** The layout is platform-neutral and the code paths are there, but
  nothing builds a macOS artifact yet (see packaging-macos.md).

## Testing it

The mechanism is covered by `tests/test_update_install.py` and
`tests/test_launcher.py` — archive safety, version selection, rollback, PID
waiting, install and prune.

Those use stand-in builds. The end-to-end check that matters is two real
packaged builds: install one, update to the other, confirm the launcher starts
the new one and the old directory is still there. Windows especially needs the
real thing, since the locked-file behaviour that motivates the whole design
does not exist on Linux.
