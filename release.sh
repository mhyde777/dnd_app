#!/usr/bin/env bash
# Cut and publish a release, end to end.
#
#   ./release.sh patch            0.4.1 -> 0.4.2
#   ./release.sh minor            0.4.1 -> 0.5.0
#   ./release.sh 1.0.0            an explicit version
#   ./release.sh patch --dry-run  say what it would do, change nothing
#   ./release.sh patch --yes      don't ask before pushing
#   ./release.sh patch --local    build and publish here instead of in CI
#
# What it does, in order:
#   1. checks the tree, the branch, the tag, gh, and runs the tests
#   2. bumps version.py and closes the changelog's Unreleased section
#   3. commits, pushes, tags with the release notes, pushes the tag
#   4. pushing the tag starts GitHub Actions, which builds Linux and Windows
#      and publishes one complete release (--local builds here instead)
#
# The checks come first on purpose. Everything after step 2 is public, and the
# cheapest moment to stop is before any of it has happened.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
BRANCH="master"

die() { echo; echo "error: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

DRY_RUN=0
ASSUME_YES=0
LOCAL_BUILD=0
BUMP=""
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --yes|-y)  ASSUME_YES=1 ;;
        --local)   LOCAL_BUILD=1 ;;
        -h|--help) sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)        die "unknown option: $arg" ;;
        *)         BUMP="$arg" ;;
    esac
done
[[ -n "$BUMP" ]] || die "say what to release: patch, minor, major, or a version
try: ./release.sh --help"

# ---- 1. is this a safe place to start from? --------------------------------

step "Checking the working tree"

[[ -z "$(git status --porcelain)" ]] || die "the working tree has uncommitted changes.
Commit or stash them: a release must correspond to a commit."

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] || die "on branch '$CURRENT_BRANCH', not '$BRANCH'."

git fetch --quiet origin "$BRANCH" 2>/dev/null || true
BEHIND="$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)"
[[ "$BEHIND" -eq 0 ]] || die "$BEHIND commit(s) on origin/$BRANCH are not here. Pull first."

command -v gh >/dev/null 2>&1 || die "the GitHub CLI (gh) is not installed.
  Debian/Ubuntu: sudo apt install gh    Windows: winget install GitHub.cli
Then: gh auth login"
gh auth status >/dev/null 2>&1 || die "gh is not logged in. Run: gh auth login"

echo "  clean, on $BRANCH, up to date with origin, gh ready"

# ---- 2. what would this release be? ----------------------------------------

step "Working out the version"
python3 scripts/prepare_release.py "$BUMP" --dry-run

NEW_VERSION="$(python3 - "$BUMP" <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
from prepare_release import bump, current_version
arg = sys.argv[1]
print(bump(current_version(), arg) if arg in ("major", "minor", "patch") else arg.lstrip("vV"))
PY
)"
TAG="v${NEW_VERSION}"

git rev-parse "$TAG" >/dev/null 2>&1 && die "tag $TAG already exists locally."
if git ls-remote --tags origin "refs/tags/$TAG" | grep -q .; then
    die "tag $TAG already exists on origin."
fi

# ---- 3. does it work? -------------------------------------------------------

step "Running the tests"
if QT_QPA_PLATFORM=offscreen pipenv run python -m pytest tests/ -q > /tmp/release-tests.log 2>&1; then
    tail -1 /tmp/release-tests.log | sed 's/^/  /'
else
    tail -20 /tmp/release-tests.log >&2
    die "tests failed. Not releasing."
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    step "--dry-run: stopping here"
    if [[ "$LOCAL_BUILD" -eq 1 ]]; then
        echo "  would release $TAG, push $BRANCH and the tag, then build and publish here."
    else
        echo "  would release $TAG, push $BRANCH and the tag, then let CI build and publish."
    fi
    exit 0
fi

# ---- 4. the point of no return ---------------------------------------------

if [[ "$ASSUME_YES" -eq 0 ]]; then
    echo
    read -r -p "Release $TAG and publish it publicly? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || die "stopped. Nothing has changed."
fi

step "Bumping the version and closing the changelog"
python3 scripts/prepare_release.py "$NEW_VERSION"

step "Committing"
NOTES_FILE="$(mktemp)"
trap 'rm -f "$NOTES_FILE"' EXIT
awk -v ver="$NEW_VERSION" '
  /^## \[/ { if (inside) exit
             l=$0; gsub(/^## \[/,"",l); gsub(/\].*$/,"",l)
             if (l == ver) { inside=1; next } }
  inside { print }
' CHANGELOG.md > "$NOTES_FILE"

git add -A
git commit -q -m "Release ${NEW_VERSION}

$(head -c 1200 "$NOTES_FILE")"
echo "  $(git log --oneline -1)"

step "Pushing $BRANCH"
git push --quiet origin "$BRANCH"
echo "  pushed"

step "Tagging $TAG"
# The tag carries the release notes, so `git show` on it explains itself even
# with no network.
git tag -a "$TAG" -F "$NOTES_FILE"
git push --quiet origin "$TAG"
echo "  tagged and pushed"

# ---- 5. build and publish ---------------------------------------------------

# Pushing the tag is the trigger: .github/workflows/release.yml builds Linux
# and Windows in parallel and publishes one complete release. This used to
# build locally and then need a second pass on the Windows machine, and a
# release missing its Windows assets leaves every Windows user's updater
# reporting "no build for this system".
#
# --local builds and publishes from here instead, for when CI is unavailable
# or a release needs repairing by hand. It produces only this platform's
# artifacts, so the other platform still has to be built somewhere.
if [[ "$LOCAL_BUILD" -eq 1 ]]; then
    step "Building and publishing locally (--local)"
    ./package.sh --publish
    echo
    echo "  Only this platform's artifacts were published. On the other machine:"
    echo "      git pull && ./package_WIN.sh --publish"
else
    step "Handing off to CI"
    echo "  The tag is pushed; GitHub Actions is building both platforms."
    if command -v gh >/dev/null 2>&1; then
        echo "  Watch it with:  gh run watch"
        echo "  Or:             gh run list --workflow=release.yml"
    fi
fi

step "Done"
echo "  $TAG: https://github.com/mhyde777/dnd_app/releases/tag/$TAG"
echo
echo "  The release is published once every artifact is attached, so it does"
echo "  not appear until the build finishes. Then: Help -> Check for Updates."
