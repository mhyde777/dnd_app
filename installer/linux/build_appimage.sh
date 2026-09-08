#!/usr/bin/env bash
#
# Builds the Linux AppImage from a tree package.sh has already staged.
#
#   build_appimage.sh <payload-dir> <launcher> <version> <arch> <output.AppImage>
#
# The AppImage is the primary Linux download: one file, mark it executable,
# double-click. No tarball to unpack, no install.sh to run in a terminal, and
# no choosing between two similarly named binaries.
#
# Assembled by hand rather than with appimagetool, for one reason: the runtime.
# An AppImage is just [runtime][squashfs] concatenated, and appimagetool's
# default runtime dynamically loads libfuse.so.2 -- which Ubuntu 22.04+ and
# Fedora no longer install. The failure is `dlopen(): error loading
# libfuse.so.2` on a double-click, for precisely the user who cannot diagnose
# it. The type2-runtime build used here is static-pie with squashfuse linked
# in, so it needs nothing from the host. Building the two pieces ourselves is
# less machinery than persuading appimagetool to use a different runtime.
set -euo pipefail

PAYLOAD_DIR="${1:?payload directory}"
LAUNCHER="${2:?launcher binary}"
VERSION="${3:?version}"
ARCH="${4:?arch}"
OUTPUT="${5:?output path}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ICON_SRC="$ROOT_DIR/images/d20_icon.png"

# Cached outside the repo: build/ and dist/ are deleted at the start of every
# build, and re-downloading a megabyte on each one is rude to both the network
# and to GitHub.
RUNTIME_CACHE="${APPIMAGE_RUNTIME_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/combat-tracker}"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-${ARCH}"
RUNTIME_FILE="$RUNTIME_CACHE/runtime-${ARCH}"

command -v mksquashfs >/dev/null 2>&1 || {
    echo "mksquashfs not found -- install squashfs-tools to build the AppImage." >&2
    exit 1
}

# ------------------------------------------------------------
# Runtime
# ------------------------------------------------------------
if [[ ! -s "$RUNTIME_FILE" ]]; then
    mkdir -p "$RUNTIME_CACHE"
    echo "Fetching AppImage runtime for ${ARCH}..."
    # To a temp name, moved only on success: an interrupted download must not
    # leave something that looks like a cached runtime and gets concatenated
    # into every future build.
    if ! curl -sSfL -o "$RUNTIME_FILE.part" "$RUNTIME_URL"; then
        rm -f "$RUNTIME_FILE.part"
        echo "Could not download the AppImage runtime from $RUNTIME_URL" >&2
        exit 1
    fi
    mv "$RUNTIME_FILE.part" "$RUNTIME_FILE"
fi
chmod 755 "$RUNTIME_FILE"

# ------------------------------------------------------------
# AppDir
# ------------------------------------------------------------
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
APPDIR="$BUILD_DIR/AppDir"

# usr/bin holds the payload *and* the launcher. Deliberately not a directory
# called `versions`: that name is what install_layout.detect() keys on, and a
# read-only mount that looked like an updatable install would offer the user a
# button that could only ever fail. See lib/app/appimage.py.
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -a "$PAYLOAD_DIR/." "$APPDIR/usr/bin/"
cp "$LAUNCHER" "$APPDIR/usr/bin/combat-tracker"
chmod 755 "$APPDIR/usr/bin/combat-tracker" "$APPDIR/usr/bin/combat_tracker"

# AppRun runs the app directly. It does not run the launcher: the launcher's
# job is to choose between installed versions, and inside an AppImage there is
# exactly one.
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# AppImage entry point. APPDIR is exported by the runtime.
HERE="$(dirname "$(readlink -f "$0")")"
export APPDIR="${APPDIR:-$HERE}"
exec "$HERE/usr/bin/combat_tracker" "$@"
APPRUN
chmod 755 "$APPDIR/AppRun"

# The spec wants the .desktop and the icon at the AppDir root; desktop
# environments read the copies under usr/share once installed.
DESKTOP_CONTENT="[Desktop Entry]
Type=Application
Name=Combat Tracker
Comment=Initiative, HP and conditions for D&D 5e
Exec=combat_tracker
Icon=combat_tracker
Terminal=false
Categories=Game;
StartupWMClass=combat_tracker
X-AppImage-Version=${VERSION}
"
printf '%s' "$DESKTOP_CONTENT" > "$APPDIR/combat-tracker.desktop"
cp "$APPDIR/combat-tracker.desktop" "$APPDIR/usr/share/applications/"

if [[ -f "$ICON_SRC" ]]; then
    cp "$ICON_SRC" "$APPDIR/combat_tracker.png"
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/combat_tracker.png"
else
    echo "warning: $ICON_SRC missing -- the AppImage will have no icon" >&2
fi

if command -v desktop-file-validate >/dev/null 2>&1; then
    # A malformed entry is accepted by the build and then silently ignored by
    # the desktop, which is the hardest kind of failure to notice.
    desktop-file-validate "$APPDIR/combat-tracker.desktop" || {
        echo "error: the generated .desktop file is not valid" >&2
        exit 1
    }
fi

# ------------------------------------------------------------
# Squash and concatenate
# ------------------------------------------------------------
SQUASH="$BUILD_DIR/payload.squashfs"
# -root-owned so the image does not carry the build user's uid; -noappend so a
# rerun replaces rather than accumulates. zstd is both smaller and faster to
# mount than the gzip default.
mksquashfs "$APPDIR" "$SQUASH" \
    -root-owned -noappend -no-progress -quiet \
    -comp zstd -Xcompression-level 19 -b 1M

mkdir -p "$(dirname "$OUTPUT")"
cat "$RUNTIME_FILE" "$SQUASH" > "$OUTPUT"
chmod 755 "$OUTPUT"

echo "AppImage: $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
