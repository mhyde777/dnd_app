#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="combat_tracker"
USER_APPS_DIR="${HOME}/.local/share/applications"

# NEW: config location
CONFIG_DIR="${HOME}/dnd_tracker_config"
CONFIG_ENV="${CONFIG_DIR}/.env"

# Ensure we run inside the pipenv environment
if [[ -z "${PIPENV_ACTIVE:-}" ]]; then
  exec pipenv run "$ROOT_DIR/package.sh" "$@"
fi

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/package"

# Correct PyInstaller module name
if ! python -m PyInstaller --version >/dev/null 2>&1; then
    echo "PyInstaller is not installed in this environment." >&2
    echo "Install it with: pip install pyinstaller" >&2
    echo "Or, if using pipenv: pipenv install --dev" >&2
    exit 1
fi

python -m PyInstaller --noconfirm --clean "$ROOT_DIR/pyinstaller.spec"

mkdir -p "$ROOT_DIR/package/opt/$APP_NAME"
mkdir -p "$ROOT_DIR/package/usr/share/applications"
mkdir -p "$ROOT_DIR/package/usr/share/icons/hicolor/scalable/apps"

if [[ -d "$ROOT_DIR/dist/$APP_NAME" ]]; then
  # onedir build
  cp -r "$ROOT_DIR/dist/$APP_NAME" "$ROOT_DIR/package/opt/"
  find "$ROOT_DIR/package/opt/$APP_NAME" -type f -exec chmod 644 -- {} +
  find "$ROOT_DIR/package/opt/$APP_NAME" -type d -exec chmod 755 -- {} +
  chmod +x "$ROOT_DIR/package/opt/$APP_NAME/$APP_NAME"
else
  # onefile build
  cp "$ROOT_DIR/dist/$APP_NAME" "$ROOT_DIR/package/opt/$APP_NAME/$APP_NAME"
  chmod 755 "$ROOT_DIR/package/opt/$APP_NAME/$APP_NAME"
fi

cp "$ROOT_DIR/images/d20_icon.png" \
  "$ROOT_DIR/package/usr/share/icons/hicolor/scalable/apps/$APP_NAME.png"
cp "$ROOT_DIR/combat_tracker.desktop" \
  "$ROOT_DIR/package/usr/share/applications"

find "$ROOT_DIR/package/usr/share" -type f -exec chmod 644 -- {} +

# ------------------------------------------------------------
# NEW: Install / overwrite runtime .env
# ------------------------------------------------------------
mkdir -p "$CONFIG_DIR"

if [[ -f "$ROOT_DIR/dnd_app/.env" ]]; then
  cp "$ROOT_DIR/dnd_app/.env" "$CONFIG_ENV"
  chmod 600 "$CONFIG_ENV"
  echo "Installed .env -> $CONFIG_ENV"
else
  echo "WARNING: dnd_app/.env not found; skipping env install" >&2
fi

# ------------------------------------------------------------
# Dev install (user-local GNOME launcher)
# ------------------------------------------------------------
mkdir -p "$USER_APPS_DIR"

BIN_PATH="$ROOT_DIR/package/opt/$APP_NAME/$APP_NAME"
ICON_PATH="$ROOT_DIR/images/d20_icon.png"

cat > "$USER_APPS_DIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Combat Tracker
Exec=$BIN_PATH
Icon=$ICON_PATH
Terminal=false
Categories=Game;
EOF

chmod 644 "$USER_APPS_DIR/$APP_NAME.desktop"

# Refresh desktop database (best-effort)
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$USER_APPS_DIR" >/dev/null 2>&1 || true
fi
