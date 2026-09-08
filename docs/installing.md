# Installing

One file, from the [latest release](https://github.com/mhyde777/dnd_app/releases/latest).
Nothing to unpack, nothing to configure, and no administrator password.

| Your system | Download | Then |
|---|---|---|
| **Windows** | `combat-tracker-…-windows-x64-setup.exe` | Run it |
| **Linux** | `combat-tracker-…-linux-x86_64.AppImage` | Make it executable, then open it |

Your encounters, characters and settings live in `~/.dnd_tracker_config`
(`%USERPROFILE%\.dnd_tracker_config` on Windows) and are never touched by
installing, updating or uninstalling.

---

## Windows

Run the `setup.exe`. It installs to your own user account rather than to
Program Files, which is why it never asks for an administrator password, and
it adds Combat Tracker to your Start Menu — a desktop shortcut is a tick box
on the way through.

### "Windows protected your PC"

You will see a blue box saying the publisher is unrecognized. Click **More
info**, then **Run anyway**.

This is SmartScreen, and it appears because the installer is not code-signed —
a certificate is an annual cost this project doesn't currently carry. The
warning is about Microsoft not recognising the file, not about anything being
wrong with it.

If you would rather verify it yourself, every release publishes a `SHA256SUMS`
file listing a fingerprint for each download. In PowerShell, in your Downloads
folder:

```powershell
Get-FileHash .\combat-tracker-0.5.1-windows-x64-setup.exe -Algorithm SHA256
```

Compare the result with the line for that filename in `SHA256SUMS`. If they
match, the file is exactly what was built.

### Uninstalling

**Settings → Apps → Installed apps → Combat Tracker → Uninstall**, the same as
any other program. Your data is deliberately left behind; the uninstaller tells
you where it is, so you can delete that folder too if you want a clean slate.

---

## Linux

The download is an **AppImage**: a single file that contains the whole
application and runs on any modern distribution without installing anything.

Before it will run, it needs to be marked executable — a Linux safety rule that
applies to anything downloaded from the web.

**In your file manager:** right-click the file → **Properties** → **Permissions**
→ tick **Allow executing file as program**. Then double-click it.

**Or in a terminal:**

```bash
chmod +x combat-tracker-*-linux-x86_64.AppImage
./combat-tracker-*-linux-x86_64.AppImage
```

### Installing it properly

The first time it runs it offers to install itself. Saying yes:

- adds Combat Tracker to your applications menu,
- lets it update itself from **Help → Check for Updates**.

It copies into `~/.local/opt/combat-tracker` and writes a menu entry to
`~/.local/share/applications`. Nothing outside your home directory is touched
and no password is needed. Once it is installed you can delete the downloaded
AppImage.

Saying **Not now** is a real answer — it keeps working from wherever you left
it, and you will not be asked again. **File → Install Combat Tracker…** does
the same thing whenever you want it.

The offer exists because an AppImage is a read-only file: it is the easiest
thing to download, but it cannot replace itself with a newer version. Installing
converts it into an ordinary installation that can.

### Uninstalling

```bash
rm -rf ~/.local/opt/combat-tracker
rm -f ~/.local/share/applications/combat-tracker.desktop
```

Add `rm -rf ~/.dnd_tracker_config` to remove your encounters and settings too.

---

## Updating

Once installed, **Help → Check for Updates** downloads and installs new
versions and restarts into them. There is an optional startup check under
**File → Settings… → Updates** that raises a banner when a newer version
exists; it only tells you, it never downloads.

[In-app updating](auto-update.md) describes what the button actually does, and
how to go back to a previous version.

### If the button says "Download" instead of "Update and Restart"

Something about where the app is installed stops it replacing itself. **Help →
Installation Details…** shows exactly which check failed — where it is
installed, whether the launcher is there, whether that folder is writable —
with a **Copy** button for pasting into a bug report. The same summary is
written to **Help → Show Log…** every time the app starts.

The usual cause on Windows is an install extracted into `C:\Program Files`,
which your account cannot write to. Installing with the `setup.exe` avoids it:
it installs under your own user account, which is always writable.

---

## The other downloads

Each release also carries a `.tar.gz` (Linux) and a `.zip` (Windows) of the
same build. These are what the in-app updater downloads, and they are the right
choice if you want a portable copy or to place the app somewhere specific
yourself. Unpack one and run `combat-tracker` — the launcher, and what a
shortcut should point at, so an update can swap the version underneath it.

`foundryvtt-bridge.zip` and `module.json` are the Foundry VTT module; see
[Connecting to Foundry VTT](foundry-setup.md).

---

## If it won't start

| What you see | What it means |
|---|---|
| Windows: "unrecognized publisher" | Expected — **More info** → **Run anyway**. See above. |
| Linux: nothing happens on double-click | The file is not marked executable yet. See above. |
| Linux: `dlopen(): error loading libfuse.so.2` | An old AppImage. Current releases need no FUSE at all — download the latest. |
| "No build for this system" when updating | The release is missing this platform's archive. Report it; meanwhile install the latest release by hand. |
| The app starts with the setup wizard again | No `settings.json` yet — fill it in once. |
