#!/usr/bin/env bash
#
# Windows build script. Run from Git Bash on a Windows machine -- PyInstaller
# cannot cross-compile, so a Windows executable has to be built on Windows.
#
#   ./package_WIN.sh                 build a release zip in dist/
#   ./package_WIN.sh --dev-install   also copy .env into %USERPROFILE%\.dnd_tracker_config
#   ./package_WIN.sh --publish       also upload to the GitHub release for this
#                                    version (needs gh, and the tag pushed)
#
# As on Linux, the release path writes nothing outside the repo: a build that
# ships someone else's credentials would be a serious mistake, so the .env copy
# is opt-in and local-only.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="combat_tracker"
DIST_NAME="combat-tracker"
LAUNCHER_NAME="combat-tracker"
CONFIG_DIR="${HOME}/.dnd_tracker_config"
CONFIG_ENV="${CONFIG_DIR}/.env"

DEV_INSTALL=0
PUBLISH=0
for arg in "$@"; do
  case "$arg" in
    --dev-install) DEV_INSTALL=1 ;;
    --publish)     PUBLISH=1 ;;
    -h|--help)
      sed -n '3,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

command -v pipenv >/dev/null 2>&1 || {
    echo "pipenv not found. Install it or run from an environment with pipenv." >&2
    exit 1
}

RUN=(pipenv run)
if [[ -n "${PIPENV_ACTIVE:-}" ]]; then
	RUN=()
fi

if ! "${RUN[@]}" python -m PyInstaller --version >/dev/null 2>&1; then
    echo "PyInstaller is not installed in this environment." >&2
    echo "Install it with: pip install pyinstaller" >&2
    echo "Or, if using pipenv: pipenv install --dev" >&2
    exit 1
fi

if [[ ! -f "$ROOT_DIR/images/d20_icon.ico" ]]; then
    echo "images/d20_icon.ico is missing -- Windows builds need the .ico, not the .png." >&2
    echo "Regenerate it with: convert images/d20_icon.png -define icon:auto-resize=256,128,64,48,32,16 images/d20_icon.ico" >&2
    exit 1
fi

# Read straight out of the file rather than by importing it. An import can be
# served from a stale __pycache__ entry -- Python validates bytecode on the
# source's mtime-in-whole-seconds and size, so an edit that keeps the length
# the same within the same second is invisible to it, and the build silently
# takes the wrong version number.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT_DIR/lib/app/version.py" | tr -d '\r')"
[[ -n "$VERSION" ]] || { echo "could not read __version__ from lib/app/version.py" >&2; exit 1; }
STAGE_NAME="${DIST_NAME}-${VERSION}-windows-x64"

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/package_win"

"${RUN[@]}" python -m PyInstaller --noconfirm --clean "$ROOT_DIR/pyinstaller.spec"

# The launcher is a separate, tiny binary. It is what the shortcut points at,
# and the one thing an update cannot replace while it is running.
"${RUN[@]}" python -m PyInstaller --noconfirm --clean "$ROOT_DIR/launcher.spec"

# ------------------------------------------------------------
# Stage the release tree
# ------------------------------------------------------------
# Layout (see lib/app/install_layout.py):
#   <root>\combat-tracker.exe   launcher, what the shortcut points at
#   <root>\versions\<ver>\      the build itself
#   <root>\current              which version to run
# An update adds a directory under versions\ and repoints current. It never
# writes to the running build -- which on Windows it could not do anyway, since
# a running .exe and its loaded DLLs are held open.
STAGE_DIR="$ROOT_DIR/package_win/$STAGE_NAME"
PAYLOAD_DIR="$STAGE_DIR/versions/$VERSION"
mkdir -p "$PAYLOAD_DIR"

if [[ -d "$ROOT_DIR/dist/$APP_NAME" ]]; then
    cp -r "$ROOT_DIR/dist/$APP_NAME/." "$PAYLOAD_DIR/"
else
    cp "$ROOT_DIR/dist/$APP_NAME.exe" "$PAYLOAD_DIR/$APP_NAME.exe"
fi

cp "$ROOT_DIR/dist/${LAUNCHER_NAME}.exe" "$STAGE_DIR/${LAUNCHER_NAME}.exe"
printf '%s\n' "$VERSION" > "$STAGE_DIR/current"

for doc in LICENSE-SRD.md; do
  [[ -f "$ROOT_DIR/$doc" ]] && cp "$ROOT_DIR/$doc" "$STAGE_DIR/"
done

cat > "$STAGE_DIR/README.txt" <<EOF
D&D Combat Tracker ${VERSION} (Windows x64)

Run: combat-tracker.exe

Run combat-tracker.exe, not the .exe under versions\\. The launcher picks which
installed version to start, and it is what lets Help -> Check for Updates
install a new version and restart into it. Starting the inner .exe directly
works, but that copy cannot update itself.

This build is not code-signed, so Windows SmartScreen will warn that it is from
an unrecognized publisher. Click "More info" then "Run anyway" to start it.

On first launch you'll be asked where to keep your data. Everything the app
writes lives in %USERPROFILE%\\.dnd_tracker_config\\ -- delete that folder to
start over.

The Foundry VTT bridge is off by default; see docs/foundry-setup.md in the
project repository to turn it on.
EOF

# ------------------------------------------------------------
# Zip
# ------------------------------------------------------------
mkdir -p "$ROOT_DIR/dist"
ZIP_PATH="$ROOT_DIR/dist/${STAGE_NAME}.zip"

if command -v zip >/dev/null 2>&1; then
    (cd "$ROOT_DIR/package_win" && zip -qr "$ZIP_PATH" "$STAGE_NAME")
elif command -v powershell.exe >/dev/null 2>&1; then
    # Git Bash usually has no zip(1); PowerShell is always there on Windows.
    powershell.exe -NoProfile -Command \
        "Compress-Archive -Path '$(cygpath -w "$ROOT_DIR/package_win/$STAGE_NAME")' -DestinationPath '$(cygpath -w "$ZIP_PATH")' -Force"
else
    echo "Neither zip nor powershell.exe found; staged tree left at $STAGE_DIR" >&2
    exit 1
fi

echo "Release artifact: $ZIP_PATH"

# Published alongside the build so the in-app updater can check what it
# downloaded. Upload both to the GitHub release.
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$ROOT_DIR/dist" && sha256sum "${STAGE_NAME}.zip" "foundryvtt-bridge.zip" > SHA256SUMS)
    echo "Checksums:        $ROOT_DIR/dist/SHA256SUMS"
fi

# ------------------------------------------------------------
# Publish (opt-in)
# ------------------------------------------------------------
# The Foundry module ships with every release; its manifest URL points at
# /releases/latest/download/, so a release without it breaks installs.
"$ROOT_DIR/package_module.sh"

if [[ "$PUBLISH" -eq 1 ]]; then
    # Uploads the zip and the checksums together, then checks the release
    # really has them -- a release with no assets looks finished but leaves
    # the in-app updater reporting "no build for this system".
    "$ROOT_DIR/publish.sh" "$ZIP_PATH" "$ROOT_DIR/dist/SHA256SUMS" \
        "$ROOT_DIR/dist/foundryvtt-bridge.zip" "$ROOT_DIR/dist/module.json"
fi

# ------------------------------------------------------------
# Dev install (opt-in, this machine only)
# ------------------------------------------------------------
if [[ "$DEV_INSTALL" -eq 1 ]]; then
    if [[ -f "$ROOT_DIR/.env" ]]; then
        mkdir -p "$CONFIG_DIR"
        cp "$ROOT_DIR/.env" "$CONFIG_ENV"
        echo "Installed .env -> $CONFIG_ENV"
    else
        echo "No .env at repo root; skipping env install" >&2
    fi
fi
