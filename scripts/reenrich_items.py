#!/usr/bin/env python3
"""
scripts/reenrich_items.py

Re-enriches all stored items using the current item_parser logic.

For items whose item_type is "other", infers the correct type from the item
name using keyword patterns, then rebuilds tags for every item.

Usage:
    pipenv run python scripts/reenrich_items.py          # dry-run (no writes)
    pipenv run python scripts/reenrich_items.py --apply  # write changes
"""
from __future__ import annotations

import argparse
import re
import sys
import os

# Make lib importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from app.item_parser import _build_tags, _TYPE_MAP


# ── Name-based type inference ─────────────────────────────────────────────────
# Ordered list of (regex, item_type) pairs. First match wins.

_NAME_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Mounts — check before generic "pack" so "riding horse" doesn't match pack
    (re.compile(r'\b(horse|mule|pony|donkey|camel|elephant|mastiff|ox|warhorse|'
                r'riding|draft\s+horse|war\s+horse|mount)\b', re.I), "mount"),

    # Packs / equipment bundles
    (re.compile(r"\bpack\b", re.I), "adventuring_gear"),

    # Druidic / arcane foci
    (re.compile(r'\b(druidic\s+focus|orb|crystal\s+focus|wand\s+focus)\b', re.I), "arcane_focus"),

    # Musical instruments
    (re.compile(r'\b(lute|flute|drum|horn|lyre|viol|pan\s+flute|shawm|'
                r'bagpipes?|dulcimer|instrument)\b', re.I), "tool"),

    # Gaming sets / artisan tools
    (re.compile(r'\b(dice\s+set|playing\s+card|chess|dragonchess|three-dragon\s+ante|'
                r'gaming\s+set)\b', re.I), "tool"),
    (re.compile(r"\bartisan'?s?\s+tools?\b", re.I), "tool"),

    # Tack / harness
    (re.compile(r'\b(saddle|bridle|bit\s+and\s+bridle|harness|feed|'
                r'saddlebags?|tack)\b', re.I), "adventuring_gear"),
]


def _infer_type_from_name(name: str) -> str | None:
    for pattern, item_type in _NAME_PATTERNS:
        if pattern.search(name):
            return item_type
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def _get_storage():
    from app import settings as _settings
    mode = _settings.get("storage_mode", "local")
    if mode == "api":
        from app.storage_api import StorageAPI
        from app.config import get_storage_api_base
        return StorageAPI(get_storage_api_base())
    else:
        from app.local_storage import LocalStorage
        from app.config import get_local_data_dir
        data_dir = get_local_data_dir()
        if not data_dir:
            print("ERROR: local_data_dir not set in settings. Run the app first to configure storage.")
            sys.exit(1)
        return LocalStorage(data_dir)


def main():
    parser = argparse.ArgumentParser(description="Re-enrich item type/tags from stored JSON.")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = parser.parse_args()

    dry_run = not args.apply
    if dry_run:
        print("DRY RUN — pass --apply to write changes\n")

    storage = _get_storage()

    keys = storage.list_item_keys()
    print(f"Found {len(keys)} items.\n")

    updated = 0
    skipped = 0
    unchanged = 0

    for key in sorted(keys):
        item = storage.get_item(key)
        if not item:
            print(f"  SKIP  {key}  (could not load)")
            skipped += 1
            continue

        name       = item.get("name", key)
        item_type  = item.get("item_type", "other")
        rarity     = item.get("rarity", "")
        subtype    = item.get("subtype", "")
        old_tags   = item.get("tags", [])

        new_type = item_type

        # Infer type for unknowns
        if item_type == "other":
            inferred = _infer_type_from_name(name)
            if inferred:
                new_type = inferred

        # Merge standard tags in — never remove existing custom tags
        standard_tags = _build_tags(new_type, rarity, subtype)
        old_tags_set  = set(old_tags)
        added_tags    = [t for t in standard_tags if t not in old_tags_set]
        new_tags      = old_tags + added_tags

        type_changed = new_type != item_type
        tags_changed = bool(added_tags)

        if not type_changed and not tags_changed:
            unchanged += 1
            continue

        # Report
        changes = []
        if type_changed:
            changes.append(f"type: {item_type!r} → {new_type!r}")
        if added_tags:
            changes.append(f"tags +{added_tags}")
        print(f"  {'WOULD UPDATE' if dry_run else 'UPDATED'}  {name}  ({', '.join(changes)})")

        if not dry_run:
            item["item_type"] = new_type
            item["tags"] = new_tags
            storage.save_item(key, item)

        updated += 1

    print(f"\n{'Would update' if dry_run else 'Updated'}: {updated}  |  Unchanged: {unchanged}  |  Skipped: {skipped}")
    if dry_run and updated > 0:
        print("\nRun with --apply to write these changes.")


if __name__ == "__main__":
    main()
