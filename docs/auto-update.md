# In-app updating: what exists, and what a one-click update would take

The app tells you a release exists and, since 0.3.0, downloads the right build
for your platform. It does not install it. This document is the plan for
closing that last gap, and an honest account of why it is the expensive part.

## Where things stand

| Step | Status |
|---|---|
| Notice a new release | Done — startup check, and Help → Check for Updates |
| Show what changed | Done — the update dialog reads the release's changelog section |
| Download the right build | Done — matched by platform and architecture, with progress and cancel |
| Verify the download | **Not done** — nothing checks the bytes |
| Replace the installed copy | **Not done** — the user unpacks it themselves |
| Relaunch into the new version | **Not done** |

`lib/app/update_check.py` holds the check, the asset matching and the
downloader. `lib/ui/update_dialog.py` is the UI. Neither ever executes what it
fetched.

## Why the last step is not a small one

**A running program cannot replace its own files on Windows.** The `.exe` and
every loaded DLL are held open, and `MoveFile` on them fails. This is the whole
reason auto-updaters are structured the way they are; it is not a detail to
work around later.

**PyInstaller one-folder builds load files lazily.** Even on Linux and macOS,
where a running binary can be unlinked, replacing the folder underneath a live
process risks it reaching for a file that changed identity mid-session. Doing
it while someone is running a combat is the worst possible time.

**The builds are unsigned.** Today a user consciously downloads an unsigned
binary and decides to run it. An updater that fetches and executes new code on
its own is a materially different proposition, and on Windows it will trip
SmartScreen on every single update. Signing is a prerequisite for this being a
good idea, not a polish item.

## Two mechanisms

### A. External updater process

1. The app downloads and verifies the archive.
2. It extracts to a staging directory *outside* the install directory.
3. It copies a small `updater` executable to a temp directory — it cannot live
   in the folder about to be replaced — and launches it with the app's PID, the
   staging path, the install path and the relaunch command.
4. The app quits.
5. The updater waits for the PID to exit (with a timeout and a hard stop),
   renames the install directory to `<install>.old`, moves staging into place,
   relaunches the app, and exits.
6. On next start the app deletes `<install>.old`.

The `.old` directory is the rollback: if the move fails halfway, the updater
puts it back.

### B. Launcher shim (recommended)

Users run a small, stable `combat-tracker` launcher instead of the app binary
directly. On every start it checks for a staged update, applies it if present,
then launches the real app.

This removes the entire "wait for the parent process to die" problem — at shim
time nothing is loaded yet — and with it the class of bugs that comes from
guessing when a process has really exited. The trade-offs are that it changes
what the desktop entry and shortcuts point at, and the shim itself is awkward
to update, so it must stay small and change rarely.

**Recommendation: B.** The PID dance in A is where these things break, and it
breaks on the machine of whoever is least able to recover from it.

## Staged plan

**Phase 0 — prerequisites.** None of this is worth starting without:

- Release artifacts actually attached to releases. `v0.2.0` currently has zero
  assets, so even the finished downloader has nothing to fetch.
- A `SHA256SUMS` file published as a release asset.
- A decision on code signing. A cert is roughly $100–400/year; the alternative
  is accepting a SmartScreen warning on every update, which undercuts the point
  of a one-click flow.

**Phase 1 — verify what was downloaded.** Fetch `SHA256SUMS` alongside the
asset and check the file before offering it. Worth doing on its own: it turns a
truncated or corrupted download from a confusing crash into a clear message.
Small, self-contained, no install machinery.

**Phase 2 — stage, don't install.** Extract the verified archive to
`~/.dnd_tracker_config/staged-update/<version>/` and record it in settings. Add
"Install on next launch" to the update dialog. Nothing is replaced yet; the
staging directory is inert and deletable.

**Phase 3 — the shim.** Ship the launcher, point the `.desktop` entry and the
Windows shortcut at it, and have it apply a staged update before launching. At
this point the flow is complete: download, verify, stage, restart, done.

**Phase 4 — one button.** Collapse the above into a single "Update and Restart"
that also offers to save the current encounter first.

## Things that will bite

- **Permissions.** The Linux dev install is `~/.local/opt/combat-tracker` and
  Windows builds are unpacked wherever the user chose — both user-writable,
  which is what makes this feasible. If anyone installs to `Program Files`, the
  update needs elevation, and the flow has to detect that and say so rather
  than failing halfway.
- **Settings migrations.** Data lives in `~/.dnd_tracker_config` and survives
  the swap untouched, which is why this is tractable at all. But a version that
  changes the shape of `settings.json` and is then rolled back leaves an old
  build reading a newer file. Either keep the format backward-compatible or
  stamp a schema version and refuse to start on one from the future.
- **Disk space.** Staging plus `.old` means up to three copies of the app
  during the swap. Check free space before starting.
- **Testing needs a Windows VM.** Interrupted downloads, a full disk, a denied
  rename, a crash mid-swap. Every one of those paths must end with a working
  installation — the failure mode is someone's tracker is dead ten minutes
  before a session.

## Estimate

Phase 1 is an afternoon. Phase 2 is a day. Phase 3 is the real work: a week or
so including Windows testing, most of it spent on the failure paths rather than
the happy one. Phase 4 is a day on top.

For a small user base, phases 1 and 2 capture most of the benefit — the user
gets a verified build in the right place and one restart applies it — at a
fraction of the risk of phase 3.
