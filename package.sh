#!/usr/bin/env bash
#
# Linux build script.
#
#   ./package.sh                 build a release tarball in dist/
#   ./package.sh --dev-install   also install to ~/.local/opt for daily use
#   ./package.sh --publish       also upload to the GitHub release for this
#                                version (needs gh, and the tag pushed)
#
# The release path deliberately touches nothing outside the repo. Installing a
# desktop entry and copying the developer's .env into ~/.dnd_tracker_config is a
# convenience for this laptop only -- a release build must never ship or write
# someone else's credentials, so it lives behind the flag.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="combat_tracker"
DIST_NAME="combat-tracker"
LAUNCHER_NAME="combat-tracker"
USER_APPS_DIR="${HOME}/.local/share/applications"
# A stable home for the dev install. Deliberately NOT under the repo: build/,
# dist/ and package/ are all deleted at the start of every build, so a launcher
# pointing into any of them breaks the next time you rebuild.
DEV_INSTALL_DIR="${DEV_INSTALL_DIR:-${HOME}/.local/opt/combat-tracker}"
CONFIG_DIR="${HOME}/.dnd_tracker_config"
CONFIG_ENV="${CONFIG_DIR}/.env"

DEV_INSTALL=0
PUBLISH=0
for arg in "$@"; do
  case "$arg" in
    --dev-install) DEV_INSTALL=1 ;;
    --publish)     PUBLISH=1 ;;
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

# The launcher is a separate, tiny binary. It is what shortcuts point at, and
# the one thing an update cannot replace while it is running.
python -m PyInstaller --noconfirm --clean "$ROOT_DIR/launcher.spec"

# ------------------------------------------------------------
# Stage the release tree
# ------------------------------------------------------------
# Layout (see lib/app/install_layout.py):
#   <root>/combat-tracker      launcher, what the .desktop entry points at
#   <root>/versions/<ver>/     the build itself
#   <root>/current             which version to run
# An update adds a directory under versions/ and repoints current; the running
# build is never written to, which is what makes updating from inside the app
# possible at all.
STAGE_DIR="$ROOT_DIR/package/$STAGE_NAME"
PAYLOAD_DIR="$STAGE_DIR/versions/$VERSION"
mkdir -p "$PAYLOAD_DIR"

if [[ -d "$ROOT_DIR/dist/$APP_NAME" ]]; then
  cp -r "$ROOT_DIR/dist/$APP_NAME/." "$PAYLOAD_DIR/"
else
  cp "$ROOT_DIR/dist/$APP_NAME" "$PAYLOAD_DIR/$APP_NAME"
fi

find "$PAYLOAD_DIR" -type f -exec chmod 644 -- {} +
find "$PAYLOAD_DIR" -type d -exec chmod 755 -- {} +
chmod 755 "$PAYLOAD_DIR/$APP_NAME"

cp "$ROOT_DIR/dist/$LAUNCHER_NAME" "$STAGE_DIR/$LAUNCHER_NAME"
chmod 755 "$STAGE_DIR/$LAUNCHER_NAME"
printf '%s\n' "$VERSION" > "$STAGE_DIR/current"

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
Exec=$HERE/combat-tracker
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

Run:      ./combat-tracker
Launcher: ./install.sh   (adds a desktop entry for your user)

Run ./combat-tracker, not the binary under versions/. The launcher is what
picks which installed version to start, and it is what makes Help -> Check for
Updates able to install a new version and restart into it. Starting the inner
binary directly works, but that copy cannot update itself.

Unpack this somewhere permanent before running install.sh -- the launcher it
writes points at wherever this folder currently is.

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

# Published alongside the build so the in-app updater can check what it
# downloaded. Upload both to the GitHub release.
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$ROOT_DIR/dist" && sha256sum "${STAGE_NAME}.tar.gz" >> SHA256SUMS)
  echo "Checksums:        $ROOT_DIR/dist/SHA256SUMS"
fi

# ------------------------------------------------------------
# Publish (opt-in)
# ------------------------------------------------------------
if [[ "$PUBLISH" -eq 1 ]]; then
  # Uploading both files together, and checking afterwards that they are
  # really on the release. A release published with no assets looks finished
  # but leaves the in-app updater reporting "no build for this system".
  "$ROOT_DIR/publish.sh" "$TARBALL" "$ROOT_DIR/dist/SHA256SUMS"
fi

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

  # Replace the payload in place so the launcher path never changes. rsync
  # --delete keeps removed files from lingering between builds; without it a
  # module deleted from the source stays in the install forever.
  # Same versioned layout as the tarball, so the dev install can exercise the
  # in-app updater. Only this version's directory is replaced -- other versions
  # installed by an update are left alone.
  mkdir -p "$DEV_INSTALL_DIR/versions/$VERSION"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$PAYLOAD_DIR/" "$DEV_INSTALL_DIR/versions/$VERSION/"
  else
    rm -rf "${DEV_INSTALL_DIR:?}/versions/$VERSION/"*
    cp -r "$PAYLOAD_DIR/." "$DEV_INSTALL_DIR/versions/$VERSION/"
  fi
  cp "$ROOT_DIR/dist/$LAUNCHER_NAME" "$DEV_INSTALL_DIR/$LAUNCHER_NAME"
  chmod 755 "$DEV_INSTALL_DIR/$LAUNCHER_NAME"
  printf '%s\n' "$VERSION" > "$DEV_INSTALL_DIR/current"
  cp "$ROOT_DIR/images/d20_icon.png" "$DEV_INSTALL_DIR/$APP_NAME.png"
  chmod 755 "$DEV_INSTALL_DIR/versions/$VERSION/$APP_NAME"

  # A flat install from before this layout leaves a stale binary at the root
  # that the .desktop entry may still point at.
  rm -rf "$DEV_INSTALL_DIR/_internal" "$DEV_INSTALL_DIR/$APP_NAME"

  mkdir -p "$USER_APPS_DIR"
  cat > "$USER_APPS_DIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Combat Tracker
Exec=$DEV_INSTALL_DIR/$LAUNCHER_NAME
Icon=$DEV_INSTALL_DIR/$APP_NAME.png
Terminal=false
Categories=Game;
EOF
  chmod 644 "$USER_APPS_DIR/$APP_NAME.desktop"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$USER_APPS_DIR" >/dev/null 2>&1 || true
  fi
  echo "Installed  -> $DEV_INSTALL_DIR/$LAUNCHER_NAME (runs versions/$VERSION)"
  echo "Launcher   -> $USER_APPS_DIR/$APP_NAME.desktop"
fi
