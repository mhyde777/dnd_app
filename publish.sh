#!/usr/bin/env bash
# Attach build artifacts to a GitHub release, and prove they landed.
#
#   ./publish.sh dist/combat-tracker-0.2.1-linux-x86_64.tar.gz dist/SHA256SUMS
#   ./package.sh --publish        (builds, then calls this)
#
# The failure this exists to prevent: publishing a release with no files on it.
# GitHub's web form puts the attach box below the notes and lets you press
# "Publish release" while the upload is still going, so a release with
# assets=0 looks identical to a finished one -- and the in-app updater then
# correctly reports "no build for this system", which reads like a bug in the
# app rather than a missing upload. Every path here ends by asking the API what
# is actually on the release.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="mhyde777/dnd_app"

die() { echo "error: $*" >&2; exit 1; }

[[ $# -gt 0 ]] || die "no artifacts given
usage: ./publish.sh <artifact> [artifact...]"

for artifact in "$@"; do
  [[ -f "$artifact" ]] || die "no such file: $artifact"
done

# A checksum file is what lets the in-app updater verify rather than skip
# verification, so its absence is worth saying out loud.
if ! printf '%s\n' "$@" | grep -qi 'SHA256SUMS'; then
  echo "warning: no SHA256SUMS among the artifacts — the updater will download" >&2
  echo "         without being able to verify. Add dist/SHA256SUMS." >&2
fi

command -v gh >/dev/null 2>&1 || die "the GitHub CLI (gh) is not installed.
  Debian/Ubuntu: sudo apt install gh
  Windows:       winget install GitHub.cli
  Then run: gh auth login"

gh auth status >/dev/null 2>&1 || die "gh is installed but not logged in. Run: gh auth login"

# Read straight out of the file rather than by importing it. An import can be
# served from a stale __pycache__ entry -- Python validates bytecode on the
# source's mtime-in-whole-seconds and size, so an edit that keeps the length
# the same within the same second is invisible to it, and the build silently
# takes the wrong version number.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT_DIR/lib/app/version.py" | tr -d '\r')"
[[ -n "$VERSION" ]] || { echo "could not read __version__ from lib/app/version.py" >&2; exit 1; }
TAG="v${VERSION}"

# --- the checks that stop a release describing the wrong code ---------------

git -C "$ROOT_DIR" rev-parse "$TAG" >/dev/null 2>&1 \
  || die "no tag $TAG. Create it first:
  git tag -a $TAG -m \"$TAG\" && git push origin $TAG"

TAG_COMMIT="$(git -C "$ROOT_DIR" rev-list -n1 "$TAG")"
HEAD_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
if [[ "$TAG_COMMIT" != "$HEAD_COMMIT" ]]; then
  echo "warning: $TAG points at ${TAG_COMMIT:0:8} but HEAD is ${HEAD_COMMIT:0:8}." >&2
  echo "         These artifacts were built from HEAD, not from the tag." >&2
fi

if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
  echo "warning: the working tree has uncommitted changes, so these artifacts" >&2
  echo "         do not correspond to any commit." >&2
fi

git -C "$ROOT_DIR" ls-remote --tags origin "refs/tags/$TAG" | grep -q . \
  || die "$TAG exists locally but not on origin. Push it first:
  git push origin $TAG"

# --- release notes straight out of the changelog ----------------------------

NOTES_FILE="$(mktemp)"
trap 'rm -f "$NOTES_FILE"' EXIT
awk -v ver="$VERSION" '
  # Section headings look like: ## [0.2.1] — 2026-08-26
  /^## \[/ {
    if (inside) exit
    line = $0
    gsub(/^## \[/, "", line); gsub(/\].*$/, "", line)
    if (line == ver) { inside = 1; next }
  }
  inside { print }
' "$ROOT_DIR/CHANGELOG.md" > "$NOTES_FILE"

if [[ ! -s "$NOTES_FILE" ]]; then
  echo "warning: CHANGELOG.md has no section for $VERSION; publishing with a bare title." >&2
  printf 'See CHANGELOG.md.\n' > "$NOTES_FILE"
fi

# --- create or update -------------------------------------------------------

if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  echo "Release $TAG exists; uploading artifacts (replacing any of the same name)."
  gh release upload "$TAG" "$@" --repo "$REPO" --clobber
else
  echo "Creating release $TAG."
  # Never a prerelease by default: /releases/latest skips those entirely, so
  # the in-app update check would keep reporting nothing.
  gh release create "$TAG" "$@" \
    --repo "$REPO" --title "$TAG" --notes-file "$NOTES_FILE" --latest
fi

# --- confirm, rather than assume -------------------------------------------

echo
echo "What is actually on the release now:"
gh release view "$TAG" --repo "$REPO" --json tagName,isDraft,isPrerelease,assets \
  --jq '"  tag: \(.tagName)  draft: \(.isDraft)  prerelease: \(.isPrerelease)",
        "  assets: \(.assets | length)",
        (.assets[] | "    \(.name)  \(.size) bytes")'

ASSET_COUNT="$(gh release view "$TAG" --repo "$REPO" --json assets --jq '.assets | length')"
if [[ "$ASSET_COUNT" -eq 0 ]]; then
  die "the release still has no assets — the upload did not take."
fi

echo
echo "Done. An installed older version will offer this on its next update check."
