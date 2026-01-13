#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="combat_tracker"
CONFIG_DIR="${HOME}/.dnd_tracker_config"
CONFIG_ENV="${CONFIG_DIR}/.env"

# Ensure we run inside the pipenv environment
if [[ -z "${PIPENV_ACTIVE:-}" ]]; then
    exec pipenv run "$ROOT_DIR/package_WIN.sh" "$@"
fi

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/package_win"

if ! python -m PyInstaller --version >/dev/null 2>&1; then
    echo "PyInstaller is not installed in this environment." >&2 
    echo "Install it with: pip install pyinstaller" >&2 
    echo "Or, if using pipenv: pipenv install --dev" >&2 
    exit 1
fi

python -m PyInstaller --noconfirm --clean "$ROOT_DIR/pyinstaller.spec"

mkdir -p "$ROOT_DIR/package_win"

if [[ -d "$ROOT_DIR/dist/$APP_NAME" ]]; then
    cp -r "$ROOT_DIR/dist/$APP_NAME" "$ROOT_DIR/package_win/"
else
    cp "$ROOT_DIR/dist/$APP_NAME.exe" "$ROOT_DIR/package_win/$APP_NAME.exe"
fi

if [[ -f "$ROOT_DIR/.env" ]]; then
    mkdir -p "$CONFIG_DIR"
    cp "$ROOT_DIR/.env" "$CONFIG_ENV"
    chmod 600 "$CONFIG_ENV" 2>/dev/null || true
    echo "Installed .env -> $CONFIG_ENV"
else
    echo "WARNING: dnd_app/.env not found; skipping env install" >&2 
fi

echo "Windows package staged at: $ROOT_DIR/package_win"
