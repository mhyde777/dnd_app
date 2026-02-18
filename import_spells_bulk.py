#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from dotenv import find_dotenv, load_dotenv

from app.bulk_spell_import import dedupe_prefer_non_legacy, parse_bulk_spells
from app.storage_api import StorageAPI


def _filter_for_import(spells, *, include_legacy: bool, dedupe: bool):
    """Apply import-time filters for legacy and incomplete third-party spells."""
    filtered = list(spells)

    # Keep legacy spells only when no non-legacy version is available.
    if not include_legacy:
        filtered = dedupe_prefer_non_legacy(filtered)
    elif dedupe:
        # Preserve existing dedupe behavior when callers opt in to dedupe.
        filtered = dedupe_prefer_non_legacy(filtered)

    # Skip entries missing full text; these are usually partial/locked previews.
    filtered = [s for s in filtered if "Missing description" not in s.warnings]

    return filtered


def _read_input(path: str | None) -> str:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


def main() -> int:
    # Mirror app behavior by loading .env in the current repo/project directory.
    load_dotenv(find_dotenv(usecwd=True), override=False)

    parser = argparse.ArgumentParser(
        description="One-time bulk spell parser for D&D Beyond pasted blocks."
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to text file containing multiple pasted spells. Reads stdin if omitted.",
    )
    parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Include blocks marked Legacy (default skips them).",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Do not dedupe by key (default dedupes and prefers non-legacy).",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Deprecated compatibility flag. Upload is now the default behavior.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report only. Do not upload to the Storage API.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("STORAGE_API_BASE", ""),
        help="Storage API base URL. Defaults to STORAGE_API_BASE env var.",
    )
    args = parser.parse_args()

    raw = _read_input(args.input)
    # Always parse legacy blocks first so we can keep them only as fallback when
    # a non-legacy entry for the same spell does not exist.
    spells = parse_bulk_spells(raw, include_legacy=True)
    spells = _filter_for_import(
        spells,
        include_legacy=args.include_legacy,
        dedupe=not args.no_dedupe,
    )

    if not spells:
        print("No parseable spells found.")
        return 1

    print(f"Parsed {len(spells)} spells")
    warning_count = 0
    for spell in spells:
        if spell.warnings:
            warning_count += 1
            print(f"- {spell.name} ({spell.key}) warnings: {', '.join(spell.warnings)}")
        else:
            print(f"- {spell.name} ({spell.key})")

    if warning_count:
        print(f"\n{warning_count} spells had parser warnings.")

    if args.dry_run:
        print("\nDry-run only. Re-run without --dry-run to PUT to Storage API.")
        return 0

    if not args.base_url:
        print(
            "No base URL set. Use --base-url or set STORAGE_API_BASE in your repo .env.",
            file=sys.stderr,
        )
        return 2

    api = StorageAPI(args.base_url)
    uploaded = 0
    failed = 0

    for spell in spells:
        try:
            api.save_spell(spell.key, spell.data)
            uploaded += 1
        except Exception as exc:
            failed += 1
            print(f"Failed upload {spell.key}: {exc}", file=sys.stderr)

    print(f"\nUpload complete: {uploaded} succeeded, {failed} failed.")
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
