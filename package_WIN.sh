#!/usr/bin/env bash
#
# Windows build script. Run from Git Bash on a Windows machine -- PyInstaller
# cannot cross-compile, so a Windows executable has to be built on Windows.
#
#   ./package_WIN.sh                 build a release zip in dist/
#   ./package_WIN.sh --dev-install   also install to %LOCALAPPDATA%\Programs for daily use
#   ./package_WIN.sh --publish       also upload to the GitHub release for this
#                                    version (needs gh, and the tag pushed)
#
# The release path deliberately touches nothing outside the repo. Installing a
# Start Menu shortcut and copying the developer's .env into ~/.dnd_tracker_config
# is a convenience for this machine only -- a release build must never ship or
# write someone else's credentials, so it lives behind the flag.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="combat_tracker"
DIST_NAME="combat-tracker"
LAUNCHER_NAME="combat-tracker"
# A stable home for the dev install. Deliberately NOT under the repo: build/,
# dist/ and package_win/ are all deleted at the start of every build, so a
# shortcut pointing into any of them breaks the next time you rebuild.
# %LOCALAPPDATA%\Programs is where per-user Windows apps belong; Git Bash
# exposes it as $LOCALAPPDATA, but fall back in case it is unset.
DEV_INSTALL_DIR="${DEV_INSTALL_DIR:-${LOCALAPPDATA:-${HOME}/AppData/Local}/Programs/combat-tracker}"
START_MENU_DIR="${APPDATA:-${HOME}/AppData/Roaming}/Microsoft/Windows/Start Menu/Programs"
CONFIG_DIR="${HOME}/.dnd_tracker_config"
CONFIG_ENV="${CONFIG_DIR}/.env"

DEV_INSTALL=0
PUBLISH=0
for arg in "$@"; do
  case "$arg" in
    --dev-install) DEV_INSTALL=1 ;;
    --publish)     PUBLISH=1 ;;
    -h|--help)
      sed -n '3,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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

# Windows holds a running .exe and its loaded DLLs open, so installing over a
# live copy fails partway and leaves a half-written version directory -- worse
# than not starting at all. Checked here rather than at the install step so it
# costs a second instead of a whole build.
if [[ "$DEV_INSTALL" -eq 1 ]] && command -v tasklist >/dev/null 2>&1; then
    if tasklist //FI "IMAGENAME eq ${LAUNCHER_NAME}.exe" 2>/dev/null | grep -qi "${LAUNCHER_NAME}.exe" \
    || tasklist //FI "IMAGENAME eq ${APP_NAME}.exe" 2>/dev/null | grep -qi "${APP_NAME}.exe"; then
        echo "Combat Tracker is running -- close it before --dev-install." >&2
        echo "Windows keeps the running .exe and its DLLs locked, so the copy would fail partway." >&2
        exit 1
    fi
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

# ------------------------------------------------------------
# Installer
# ------------------------------------------------------------
# Built from the tree already staged above, so the installer and the zip ship
# the identical build rather than two builds that merely agree.
#
# The zip is still published: the in-app updater unpacks it into versions/, and
# it is the escape hatch for anyone who would rather not run an installer. The
# installer is what a first-time user should be clicking -- see
# installer/windows/combat-tracker.iss for why.
ISS_FILE="$ROOT_DIR/installer/windows/combat-tracker.iss"
INSTALLER_PATH=""

find_iscc() {
    # PATH first, then the two default install locations. Inno's compiler is
    # not on PATH by default, and telling someone to fix their PATH to build a
    # release is exactly the kind of friction this whole change is removing.
    if command -v iscc >/dev/null 2>&1; then command -v iscc; return 0; fi
    if command -v ISCC.exe >/dev/null 2>&1; then command -v ISCC.exe; return 0; fi
    local candidate
    for candidate in \
        "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
        "/c/Program Files/Inno Setup 6/ISCC.exe"; do
        [[ -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
    done
    return 1
}

if ISCC="$(find_iscc)"; then
    # ISCC is a native Windows program: every path it is handed has to be a
    # Windows path, not the Git Bash view of one.
    #
    # MSYS2_ARG_CONV_EXCL is what keeps it that way. Git Bash rewrites any
    # argument that looks like a POSIX path before a native program sees it,
    # and "/DAppVersion=0.6.0" looks exactly like one -- it arrives mangled
    # into something ISCC reads as a second script filename, and the compiler
    # stops with "You may not specify more than one script filename". The
    # switches are already correct; conversion has to be turned off, not
    # worked around.
    MSYS2_ARG_CONV_EXCL="*" MSYS_NO_PATHCONV=1 \
    "$ISCC" \
        "/DAppVersion=$VERSION" \
        "/DStageDir=$(cygpath -w "$STAGE_DIR")" \
        "/DOutputDir=$(cygpath -w "$ROOT_DIR/dist")" \
        ${SIGN_INSTALLER:+/DSign} \
        "$(cygpath -w "$ISS_FILE")"
    # Not ${STAGE_NAME}-setup.exe: that name contains "windows", and every
    # updater released before 0.6.0 picks by platform token with no suffix
    # filter, so it would choose the installer over the zip and fail to
    # unpack it. Keep "win" out of this name entirely -- the old token list
    # matches the bare substring.
    INSTALLER_PATH="$ROOT_DIR/dist/${DIST_NAME}-${VERSION}-x64-setup.exe"
    if [[ -f "$INSTALLER_PATH" ]]; then
        echo "Installer:        $INSTALLER_PATH"
    else
        echo "error: ISCC reported success but produced no installer" >&2
        exit 1
    fi
else
    # Not fatal: the zip is a complete, working release on its own. But it is
    # the artifact most users are meant to download, so silence would be wrong.
    echo "warning: Inno Setup (ISCC.exe) not found -- no installer built." >&2
    echo "         Install it with: winget install JRSoftware.InnoSetup" >&2
fi


# The Foundry module ships with every release; its manifest URL points at
# /releases/latest/download/, so a release without it breaks installs.
# It is built before the checksums, not after, because SHA256SUMS lists
# foundryvtt-bridge.zip -- package.sh has always had this order, and having it
# the other way round here meant sha256sum was asked to hash a file that did
# not exist yet.
"$ROOT_DIR/package_module.sh"

# Published alongside the build so the in-app updater can check what it
# downloaded. Upload both to the GitHub release.
# Every artifact is listed, the installer included: SHA256SUMS is what someone
# who cares can check an unsigned .exe against, and with no code signature it
# is the only integrity story the Windows download has.
if command -v sha256sum >/dev/null 2>&1; then
    SUM_FILES=("${STAGE_NAME}.zip" "foundryvtt-bridge.zip")
    [[ -n "$INSTALLER_PATH" ]] && SUM_FILES+=("$(basename "$INSTALLER_PATH")")
    (cd "$ROOT_DIR/dist" && sha256sum "${SUM_FILES[@]}" > SHA256SUMS)
    echo "Checksums:        $ROOT_DIR/dist/SHA256SUMS"
fi

# ------------------------------------------------------------
# Publish (opt-in)
# ------------------------------------------------------------

if [[ "$PUBLISH" -eq 1 ]]; then
    # Uploads the zip and the checksums together, then checks the release
    # really has them -- a release with no assets looks finished but leaves
    # the in-app updater reporting "no build for this system".
    PUBLISH_FILES=("$ZIP_PATH" "$ROOT_DIR/dist/SHA256SUMS"
                   "$ROOT_DIR/dist/foundryvtt-bridge.zip" "$ROOT_DIR/dist/module.json")
    [[ -n "$INSTALLER_PATH" ]] && PUBLISH_FILES+=("$INSTALLER_PATH")
    "$ROOT_DIR/publish.sh" "${PUBLISH_FILES[@]}"
fi

# ------------------------------------------------------------
# Dev install (opt-in, this machine only)
# ------------------------------------------------------------
if [[ "$DEV_INSTALL" -eq 1 ]]; then
    mkdir -p "$CONFIG_DIR"
    if [[ -f "$ROOT_DIR/.env" ]]; then
        cp "$ROOT_DIR/.env" "$CONFIG_ENV"
        echo "Installed .env -> $CONFIG_ENV"
    else
        echo "No .env at repo root; skipping env install" >&2
    fi

    # Same versioned layout as the zip, so the dev install can exercise the
    # in-app updater. Only this version's directory is replaced -- other
    # versions installed by an update are left alone, which is the rollback.
    mkdir -p "$DEV_INSTALL_DIR/versions/$VERSION"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete "$PAYLOAD_DIR/" "$DEV_INSTALL_DIR/versions/$VERSION/"
    else
        # Git Bash ships no rsync. Clear the directory first so a module
        # deleted from the source does not linger in the install forever.
        rm -rf "${DEV_INSTALL_DIR:?}/versions/$VERSION/"*
        cp -r "$PAYLOAD_DIR/." "$DEV_INSTALL_DIR/versions/$VERSION/"
    fi
    cp "$ROOT_DIR/dist/${LAUNCHER_NAME}.exe" "$DEV_INSTALL_DIR/${LAUNCHER_NAME}.exe"
    printf '%s\n' "$VERSION" > "$DEV_INSTALL_DIR/current"
    cp "$ROOT_DIR/images/d20_icon.ico" "$DEV_INSTALL_DIR/$APP_NAME.ico"

    # A flat install from before this layout leaves a stale binary at the root
    # that a shortcut may still point at.
    rm -rf "$DEV_INSTALL_DIR/_internal" "$DEV_INSTALL_DIR/$APP_NAME.exe"

    # The Start Menu shortcut is the Windows counterpart of the .desktop entry
    # package.sh writes. It points at the launcher, never at versions\ -- that
    # is what lets Help -> Check for Updates swap the version underneath it.
    if command -v powershell.exe >/dev/null 2>&1; then
        mkdir -p "$START_MENU_DIR"
        SHORTCUT_WIN="$(cygpath -w "$START_MENU_DIR/Combat Tracker.lnk")"
        TARGET_WIN="$(cygpath -w "$DEV_INSTALL_DIR/${LAUNCHER_NAME}.exe")"
        WORKDIR_WIN="$(cygpath -w "$DEV_INSTALL_DIR")"
        ICON_WIN="$(cygpath -w "$DEV_INSTALL_DIR/$APP_NAME.ico")"
        if powershell.exe -NoProfile -Command "
            \$s = (New-Object -ComObject WScript.Shell).CreateShortcut('$SHORTCUT_WIN')
            \$s.TargetPath = '$TARGET_WIN'
            \$s.WorkingDirectory = '$WORKDIR_WIN'
            \$s.IconLocation = '$ICON_WIN'
            \$s.Description = 'D&D Combat Tracker'
            \$s.Save()" >/dev/null 2>&1; then
            echo "Start Menu -> $START_MENU_DIR/Combat Tracker.lnk"
        else
            # Not worth failing the install over -- the launcher still runs.
            echo "warning: could not create the Start Menu shortcut" >&2
        fi
    fi

    echo "Installed  -> $DEV_INSTALL_DIR\\${LAUNCHER_NAME}.exe (runs versions/$VERSION)"
fi
