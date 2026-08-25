#!/usr/bin/env python3
"""
Bulk-import pasted D&D Beyond item lists into your library.

The companion to scripts/import_spells_bulk.py, for items rather than spells.
Paste item pages into text files, then hand the whole lot to this script:

    pipenv run python scripts/import_items_bulk.py items/*.txt

Unlike the spell importer it takes any number of files, so there is no need
for a shell loop over page_1.txt, page_2.txt, ... Duplicates are resolved
across the whole run, not per file.

By default it **skips items already in your library**, so a re-run adds only
what is new and never overwrites an entry you have edited or one that came
from the bundled SRD. Pass --overwrite when you actually mean to replace.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Sequence

from dotenv import find_dotenv, load_dotenv

from app import config
from app.bulk_item_import import (
    ParsedItemBlock,
    dedupe_prefer_non_legacy,
    parse_bulk_items,
)


def gather_inputs(paths: Sequence[str]) -> list[str]:
    """Expand the given paths into a list of files to read.

    A directory contributes its *.txt files, sorted, so pointing at the folder
    you have been pasting into does the obvious thing.
    """
    files: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            files.extend(
                os.path.join(path, name)
                for name in sorted(os.listdir(path))
                if name.lower().endswith(".txt")
            )
        else:
            files.append(path)
    return files


def plan_uploads(
    items: Iterable[ParsedItemBlock],
    existing: Iterable[str],
    *,
    overwrite: bool,
) -> tuple[list[ParsedItemBlock], list[ParsedItemBlock]]:
    """Split parsed items into (to upload, skipped because already present)."""
    if overwrite:
        return list(items), []

    present = set(existing)
    upload: list[ParsedItemBlock] = []
    skipped: list[ParsedItemBlock] = []
    for item in items:
        (skipped if item.key in present else upload).append(item)
    return upload, skipped


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _open_storage(args):
    """The backend to write to: an explicit local directory, or the API."""
    if args.local_dir:
        from app.local_storage import LocalStorage
        return LocalStorage(args.local_dir), args.local_dir

    if not args.base_url:
        print(
            "No storage target. Set the API base URL in Settings → Storage, or "
            "pass --base-url, or use --local-dir to write to a folder.",
            file=sys.stderr,
        )
        return None, ""

    from app.storage_api import StorageAPI
    return StorageAPI(args.base_url), args.base_url


def main() -> int:
    # Mirror app behaviour: repo .env first, then whatever config.py loads.
    load_dotenv(find_dotenv(usecwd=True), override=False)

    parser = argparse.ArgumentParser(
        description="Bulk-import pasted D&D Beyond item blocks into your library.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Text files, or directories of .txt files. Reads stdin if omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report only; write nothing.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace entries already in the library (default: leave them alone).",
    )
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="Drop blocks marked Legacy entirely. By default a legacy block is "
             "kept only when no non-legacy version of the same item was found.",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Upload every parsed block, including duplicate keys.",
    )
    parser.add_argument(
        "--base-url",
        default=config.get_storage_api_base(),
        help="Storage API base URL. Defaults to your configured storage API.",
    )
    parser.add_argument(
        "--local-dir",
        default="",
        help="Write to this local data directory instead of the API.",
    )
    args = parser.parse_args()

    files = gather_inputs(args.inputs)
    if not files and not args.inputs:
        sources = [("<stdin>", sys.stdin.read())]
    else:
        if not files:
            print("No input files found.", file=sys.stderr)
            return 1
        sources = []
        for path in files:
            try:
                sources.append((path, _read(path)))
            except OSError as exc:
                print(f"Could not read {path}: {exc}", file=sys.stderr)
                return 1

    # Parse legacy blocks throughout, so dedupe can prefer the non-legacy
    # version of an item that appears in two different files.
    items: list[ParsedItemBlock] = []
    for path, raw in sources:
        found = parse_bulk_items(raw, include_legacy=True)
        print(f"{path}: {len(found)} parsed")
        items.extend(found)

    if not args.no_dedupe:
        before = len(items)
        items = dedupe_prefer_non_legacy(items)
        if before != len(items):
            print(f"Deduped {before} blocks to {len(items)} items")

    if args.skip_legacy:
        kept = [i for i in items if not i.is_legacy]
        if len(kept) != len(items):
            print(f"Dropped {len(items) - len(kept)} legacy items")
        items = kept

    if not items:
        print("No parseable items found.")
        return 1

    warned = [i for i in items if i.warnings]
    for item in warned:
        print(f"- {item.name} ({item.key}): {', '.join(item.warnings)}")
    if warned:
        print(f"{len(warned)} of {len(items)} items had parser warnings.")

    if args.dry_run:
        print(f"\nDry run: {len(items)} items parsed, nothing written.")
        for item in sorted(items, key=lambda i: i.key):
            print(f"  {item.key}")
        return 0

    storage, destination = _open_storage(args)
    if storage is None:
        return 2

    try:
        existing = storage.list_item_keys() or []
    except Exception as exc:
        # Not being able to list is not a reason to refuse the import, but it
        # does mean nothing can be skipped -- so say so rather than silently
        # overwriting what we could not see.
        print(f"Could not list existing items ({exc}); nothing will be skipped.",
              file=sys.stderr)
        existing = []

    upload, skipped = plan_uploads(items, existing, overwrite=args.overwrite)

    for item in skipped:
        print(f"Already present, left alone: {item.key}")

    uploaded = 0
    failed = 0
    for item in upload:
        try:
            storage.save_item(item.key, item.data)
            uploaded += 1
        except Exception as exc:
            failed += 1
            print(f"Failed to save {item.key}: {exc}", file=sys.stderr)

    print(
        f"\n{destination}: {uploaded} saved, {len(skipped)} skipped, {failed} failed."
    )
    if skipped and not args.overwrite:
        print("Re-run with --overwrite to replace the skipped entries.")
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
