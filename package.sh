#!/usr/bin/env bash
#
# Linux build script.
#
#   ./package.sh                 build a release tarball in dist/
#   ./package.sh --dev-install   also install a launcher and .env on THIS machine
#
# The release path deliberately touches nothing outside the repo. Installing a
# desktop entry and copying the developer's .env into ~/.dnd_tracker_config is a
# convenience for this laptop only -- a release build must never ship or write
# someone else's credentials, so it lives behind the flag.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="combat_tracker"
DIST_NAME="combat-tracker"
USER_APPS_DIR="${HOME}/.local/share/applications"
CONFIG_DIR="${HOME}/.dnd_tracker_config"
CONFIG_ENV="${CONFIG_DIR}/.env"

DEV_INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --dev-install) DEV_INSTALL=1 ;;
    -h|--help)
      sed -n '3,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

# Ensure we run inside the pipenv environment
if [[ -z "${PIPENV_ACTIVE:-}" ]]; then
  exec pipenv run "$ROOT_DIR/package.sh" "$@"
fi

if ! python -m PyInstaller --version >/dev/null 2>&1; then
    echo "PyInstaller is not installed in this environment." >&2
    echo "Install it with: pip install pyinstaller" >&2
    echo "Or, if using pipenv: pipenv install --dev" >&2
    exit 1
fi

VERSION="$(PYTHONPATH="$ROOT_DIR/lib" python -c 'from app.version import __version__; print(__version__)')"
ARCH="$(uname -m)"
STAGE_NAME="${DIST_NAME}-${VERSION}-linux-${ARCH}"

rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist" "$ROOT_DIR/package"

python -m PyInstaller --noconfirm --clean "$ROOT_DIR/pyinstaller.spec"

# ------------------------------------------------------------
# Stage the release tree
# ------------------------------------------------------------
STAGE_DIR="$ROOT_DIR/package/$STAGE_NAME"
mkdir -p "$STAGE_DIR"

if [[ -d "$ROOT_DIR/dist/$APP_NAME" ]]; then
  cp -r "$ROOT_DIR/dist/$APP_NAME" "$STAGE_DIR/"
else
  mkdir -p "$STAGE_DIR/$APP_NAME"
  cp "$ROOT_DIR/dist/$APP_NAME" "$STAGE_DIR/$APP_NAME/$APP_NAME"
fi

find "$STAGE_DIR/$APP_NAME" -type f -exec chmod 644 -- {} +
find "$STAGE_DIR/$APP_NAME" -type d -exec chmod 755 -- {} +
chmod 755 "$STAGE_DIR/$APP_NAME/$APP_NAME"

cp "$ROOT_DIR/images/d20_icon.png" "$STAGE_DIR/$APP_NAME.png"
for doc in LICENSE-SRD.md; do
  [[ -f "$ROOT_DIR/$doc" ]] && cp "$ROOT_DIR/$doc" "$STAGE_DIR/"
done

# A .desktop file can't be shipped ready-made: Exec and Icon have to be
# absolute, and we don't know where the user will unpack this. install.sh
# fills them in at install time.
cat > "$STAGE_DIR/install.sh" <<'INSTALL'
#!/usr/bin/env bash
# Installs a desktop launcher for the current user. Run from this directory.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS_DIR="${HOME}/.local/share/applications"
mkdir -p "$APPS_DIR"
cat > "$APPS_DIR/combat_tracker.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Combat Tracker
Exec=$HERE/combat_tracker/combat_tracker
Icon=$HERE/combat_tracker.png
Terminal=false
Categories=Game;
EOF
chmod 644 "$APPS_DIR/combat_tracker.desktop"
command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
echo "Installed launcher -> $APPS_DIR/combat_tracker.desktop"
INSTALL
chmod 755 "$STAGE_DIR/install.sh"

cat > "$STAGE_DIR/README.txt" <<EOF
D&D Combat Tracker ${VERSION} (Linux ${ARCH})

Run:      ./combat_tracker/combat_tracker
Launcher: ./install.sh   (adds a desktop entry for your user)

On first launch you'll be asked where to keep your data. Everything the app
writes lives in ~/.dnd_tracker_config/ -- delete that directory to start over.

The Foundry VTT bridge is off by default; see docs/foundry-bridge.md in the
project repository to turn it on.
EOF

# ------------------------------------------------------------
# Tarball
# ------------------------------------------------------------
mkdir -p "$ROOT_DIR/dist"
TARBALL="$ROOT_DIR/dist/${STAGE_NAME}.tar.gz"
tar -C "$ROOT_DIR/package" -czf "$TARBALL" "$STAGE_NAME"
echo "Release artifact: $TARBALL"

# ------------------------------------------------------------
# Dev install (opt-in, this machine only)
# ------------------------------------------------------------
if [[ "$DEV_INSTALL" -eq 1 ]]; then
  mkdir -p "$CONFIG_DIR"
  if [[ -f "$ROOT_DIR/.env" ]]; then
    cp "$ROOT_DIR/.env" "$CONFIG_ENV"
    chmod 600 "$CONFIG_ENV"
    echo "Installed .env -> $CONFIG_ENV"
  else
    echo "No .env at repo root; skipping env install" >&2
  fi

  mkdir -p "$USER_APPS_DIR"
  cat > "$USER_APPS_DIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Combat Tracker
Exec=$STAGE_DIR/$APP_NAME/$APP_NAME
Icon=$ROOT_DIR/images/d20_icon.png
Terminal=false
Categories=Game;
EOF
  chmod 644 "$USER_APPS_DIR/$APP_NAME.desktop"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$USER_APPS_DIR" >/dev/null 2>&1 || true
  fi
  echo "Dev launcher -> $USER_APPS_DIR/$APP_NAME.desktop"
fi
