#!/usr/bin/env bash
#
# Windows build script. Run from Git Bash on a Windows machine -- PyInstaller
# cannot cross-compile, so a Windows executable has to be built on Windows.
#
#   ./package_WIN.sh                 build a release zip in dist/
#   ./package_WIN.sh --dev-install   also copy .env into %USERPROFILE%\.dnd_tracker_config
#
# As on Linux, the release path writes nothing outside the repo: a build that
# ships someone else's credentials would be a serious mistake, so the .env copy
# is opt-in and local-only.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="combat_tracker"
DIST_NAME="combat-tracker"
CONFIG_DIR="${HOME}/.dnd_tracker_config"
CONFIG_ENV="${CONFIG_DIR}/.env"

DEV_INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --dev-install) DEV_INSTALL=1 ;;
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

VERSION="$(PYTHONPATH="$ROOT_DIR/lib" "${RUN[@]}" python -c 'from app.version import __version__; print(__version__)' | tr -d '\r')"
STAGE_NAME="${DIST_NAME}-${VERSION}-windows-x64"

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/package_win"

"${RUN[@]}" python -m PyInstaller --noconfirm --clean "$ROOT_DIR/pyinstaller.spec"

# ------------------------------------------------------------
# Stage the release tree
# ------------------------------------------------------------
STAGE_DIR="$ROOT_DIR/package_win/$STAGE_NAME"
mkdir -p "$STAGE_DIR"

if [[ -d "$ROOT_DIR/dist/$APP_NAME" ]]; then
    cp -r "$ROOT_DIR/dist/$APP_NAME" "$STAGE_DIR/"
else
    mkdir -p "$STAGE_DIR/$APP_NAME"
    cp "$ROOT_DIR/dist/$APP_NAME.exe" "$STAGE_DIR/$APP_NAME/$APP_NAME.exe"
fi

for doc in LICENSE-SRD.md; do
  [[ -f "$ROOT_DIR/$doc" ]] && cp "$ROOT_DIR/$doc" "$STAGE_DIR/"
done

cat > "$STAGE_DIR/README.txt" <<EOF
D&D Combat Tracker ${VERSION} (Windows x64)

Run: combat_tracker\\combat_tracker.exe

This build is not code-signed, so Windows SmartScreen will warn that it is from
an unrecognized publisher. Click "More info" then "Run anyway" to start it.

On first launch you'll be asked where to keep your data. Everything the app
writes lives in %USERPROFILE%\\.dnd_tracker_config\\ -- delete that folder to
start over.

The Foundry VTT bridge is off by default; see docs/foundry-bridge.md in the
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
