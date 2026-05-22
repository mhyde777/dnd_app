#!/usr/bin/env python3
"""
scripts/repair_spell_keys.py

Renames stored spell files whose storage key was generated with the old
apostrophe-to-underscore behavior (e.g. tasha_s_hideous_laughter.json)
to the new key format that strips apostrophes cleanly
(e.g. tashas_hideous_laughter.json).

The stored JSON's "name" field is used as the source of truth; the new
key is derived from it via the current spell_key() function.

Usage:
    pipenv run python scripts/repair_spell_keys.py          # dry-run (no writes)
    pipenv run python scripts/repair_spell_keys.py --apply  # rename files
"""
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from app.spell_parser import spell_key as _new_spell_key
import re as _re


def _legacy_spell_key(name: str) -> str:
    """Old key generation (apostrophe → underscore)."""
    key = name.strip().lower()
    key = _re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return f"{key}.json"


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
    parser = argparse.ArgumentParser(description="Repair spell storage keys affected by apostrophe handling.")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = parser.parse_args()

    dry_run = not args.apply
    if dry_run:
        print("DRY RUN — pass --apply to rename files\n")

    storage = _get_storage()
    keys = storage.list_spell_keys()
    print(f"Found {len(keys)} spells.\n")

    renamed = 0
    skipped = 0
    unchanged = 0

    for old_key in sorted(keys):
        data = storage.get_spell(old_key)
        if not data:
            print(f"  SKIP  {old_key}  (could not load)")
            skipped += 1
            continue

        name = data.get("name", "")
        if not name:
            print(f"  SKIP  {old_key}  (no name field)")
            skipped += 1
            continue

        new_key = _new_spell_key(name)
        legacy_key = _legacy_spell_key(name)

        if old_key == new_key:
            unchanged += 1
            continue

        if old_key != legacy_key:
            # Key doesn't match either format — unexpected, don't touch it
            print(f"  SKIP  {old_key}  (key doesn't match name '{name}', expected '{legacy_key}')")
            skipped += 1
            continue

        print(f"  {'WOULD RENAME' if dry_run else 'RENAMED'}  {old_key}  →  {new_key}  ('{name}')")

        if not dry_run:
            if new_key in keys or storage.get_spell(new_key) is not None:
                print(f"            WARNING: {new_key} already exists — skipping to avoid overwrite")
                skipped += 1
                continue
            storage.save_spell(new_key, data)
            storage.delete_spell(old_key)

        renamed += 1

    print(f"\n{'Would rename' if dry_run else 'Renamed'}: {renamed}  |  Unchanged: {unchanged}  |  Skipped: {skipped}")
    if dry_run and renamed > 0:
        print("\nRun with --apply to write these changes.")


if __name__ == "__main__":
    main()
