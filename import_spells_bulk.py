#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys

from dotenv import find_dotenv, load_dotenv

from app.bulk_spell_import import dedupe_prefer_non_legacy, parse_bulk_spells
from app.storage_api import StorageAPI


_LEGACY_NAME_RE = re.compile(r"\blegacy\b", re.IGNORECASE)


def _canonical_spell_key(key: str) -> str:
    stem = key.strip().lower()
    if stem.endswith(".json"):
        stem = stem[:-5]
    stem = re.sub(r"(?:_|\(|\[)?legacy(?:\)|\])?$", "", stem).strip("_ ")
    return f"{stem}.json" if stem else key


def _spell_is_legacy(*, key: str, data: dict | None) -> bool:
    if _LEGACY_NAME_RE.search(key.replace("_", " ")):
        return True
    if not isinstance(data, dict):
        return False
    if bool(data.get("legacy")):
        return True
    name = str(data.get("name", ""))
    source = str(data.get("source", ""))
    return bool(_LEGACY_NAME_RE.search(name) or _LEGACY_NAME_RE.search(source))


def _prepare_api_replacements(api: StorageAPI, spells) -> tuple[set[str], set[str]]:
    """
    Decide which existing API entries to delete and which parsed spells to skip.

    - If a non-legacy spell exists, skip uploading a legacy variant.
    - If uploading non-legacy and a legacy variant exists, delete legacy first.
    - If uploading legacy and only non-legacy exists, keep non-legacy and skip legacy.
    """
    existing_by_canonical: dict[str, list[str]] = {}
    for existing_key in api.list_spell_keys():
        existing_by_canonical.setdefault(_canonical_spell_key(existing_key), []).append(existing_key)

    delete_keys: set[str] = set()
    skip_upload_keys: set[str] = set()

    for spell in spells:
        canonical_key = _canonical_spell_key(spell.key)
        existing_matches = existing_by_canonical.get(canonical_key, [])
        if not existing_matches:
            continue

        for existing_key in existing_matches:
            if existing_key == spell.key:
                continue
            existing_data = api.get_spell(existing_key)
            existing_is_legacy = _spell_is_legacy(key=existing_key, data=existing_data)
            incoming_is_legacy = spell.is_legacy

            if incoming_is_legacy:
                if not existing_is_legacy:
                    skip_upload_keys.add(spell.key)
                else:
                    delete_keys.add(existing_key)
            else:
                delete_keys.add(existing_key)

    return delete_keys, skip_upload_keys


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
    try:
        delete_keys, skip_upload_keys = _prepare_api_replacements(api, spells)
    except Exception as exc:
        print(f"Failed to inspect existing spells in Storage API: {exc}", file=sys.stderr)
        return 4

    for key in sorted(delete_keys):
        try:
            api.delete_spell(key)
            print(f"Deleted existing spell variant: {key}")
        except Exception as exc:
            print(f"Failed deleting existing spell variant {key}: {exc}", file=sys.stderr)

    uploaded = 0
    failed = 0
    skipped = 0

    for spell in spells:
        if spell.key in skip_upload_keys:
            skipped += 1
            print(
                f"Skipping legacy spell {spell.key}: non-legacy variant already exists in API."
            )
            continue
        try:
            api.save_spell(spell.key, spell.data)
            uploaded += 1
        except Exception as exc:
            failed += 1
            print(f"Failed upload {spell.key}: {exc}", file=sys.stderr)

    print(f"\nUpload complete: {uploaded} succeeded, {skipped} skipped, {failed} failed.")
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
