#!/usr/bin/env python3
"""
Bump the version and close the changelog's Unreleased section.

    python3 scripts/prepare_release.py 0.4.2
    python3 scripts/prepare_release.py patch      # or minor / major
    python3 scripts/prepare_release.py patch --dry-run

Separate from release.sh so the fiddly part -- editing two files consistently
-- can be run and inspected on its own, and so a mistake here is a diff you can
read rather than something that already happened.

It refuses to prepare a release with no changelog entries. A version whose
notes say nothing is worse than no release: the in-app "What's New" reads that
section, and an empty one falls back to showing the entire history.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "lib", "app", "version.py")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
REPO = "https://github.com/mhyde777/dnd_app"

_VERSION_LINE = re.compile(r'^__version__ = "(.*)"$', re.M)


def current_version() -> str:
    """Read it as text. An import can be served from a stale __pycache__."""
    with open(VERSION_FILE, "r", encoding="utf-8") as handle:
        match = _VERSION_LINE.search(handle.read())
    if not match:
        raise SystemExit(f"no __version__ in {VERSION_FILE}")
    return match.group(1)


def bump(version: str, part: str) -> str:
    numbers = [int(p) for p in version.split(".")[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    major, minor, patch = numbers
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def unreleased_entries(text: str) -> list:
    """The bullet lines currently under Unreleased."""
    body = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## ["):
            if inside:
                break
            inside = line.startswith("## [Unreleased]")
            continue
        if inside:
            body.append(line)
    return [line for line in body if line.strip().startswith("- ")]


def rewrite_changelog(text: str, version: str, today: str) -> str:
    if f"## [{version}]" in text:
        raise SystemExit(f"CHANGELOG.md already has a section for {version}")
    if "## [Unreleased]" not in text:
        raise SystemExit("CHANGELOG.md has no [Unreleased] section")

    text = text.replace(
        "## [Unreleased]\n",
        f"## [Unreleased]\n\n## [{version}] — {today}\n",
        1,
    )

    # Link refs at the foot: point Unreleased at the new tag, and add a compare
    # link for the release itself.
    previous = None
    for match in re.finditer(r"^\[(\d+\.\d+\.\d+)\]:", text, re.M):
        previous = match.group(1)
        break
    unreleased_ref = re.search(r"^\[Unreleased\]: .*$", text, re.M)
    if unreleased_ref and previous:
        new_refs = (
            f"[Unreleased]: {REPO}/compare/v{version}...HEAD\n"
            f"[{version}]: {REPO}/compare/v{previous}...v{version}"
        )
        text = text[:unreleased_ref.start()] + new_refs + text[unreleased_ref.end():]
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("version", help="an explicit version, or major/minor/patch")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would change and touch nothing")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    now = current_version()
    if args.version in ("major", "minor", "patch"):
        version = bump(now, args.version)
    else:
        version = args.version.lstrip("vV")
        if not re.match(r"^\d+\.\d+\.\d+([-+].+)?$", version):
            raise SystemExit(f"not a version: {args.version}")

    with open(CHANGELOG, "r", encoding="utf-8") as handle:
        changelog = handle.read()

    entries = unreleased_entries(changelog)
    if not entries:
        raise SystemExit(
            "CHANGELOG.md has nothing under [Unreleased].\n"
            "A release with no notes is worse than no release: Help -> What's New\n"
            "reads that section, and an empty one falls back to the whole history."
        )

    updated = rewrite_changelog(changelog, version, args.date)

    print(f"  {now}  ->  {version}")
    print(f"  {len(entries)} changelog {'entry' if len(entries) == 1 else 'entries'}:")
    for line in entries[:8]:
        print(f"    {line.strip()[:96]}")
    if len(entries) > 8:
        print(f"    … and {len(entries) - 8} more")

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return 0

    with open(VERSION_FILE, "r", encoding="utf-8") as handle:
        version_source = handle.read()
    with open(VERSION_FILE, "w", encoding="utf-8") as handle:
        handle.write(_VERSION_LINE.sub(f'__version__ = "{version}"', version_source, count=1))
    with open(CHANGELOG, "w", encoding="utf-8") as handle:
        handle.write(updated)

    print(f"\n  wrote {os.path.relpath(VERSION_FILE, ROOT)} and "
          f"{os.path.relpath(CHANGELOG, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
