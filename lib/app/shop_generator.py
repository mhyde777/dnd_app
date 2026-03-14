# app/shop_generator.py
from __future__ import annotations

import random
from typing import Optional


# ── Builtin profiles ──────────────────────────────────────────────────────────

BUILTIN_PROFILES: dict[str, dict] = {
    "general_store": {
        "name": "General Store",
        "slots": [
            {"label": "Adventuring Gear",  "tags": ["adventuring_gear"],       "count": (5, 10), "qty": (1, 10)},
            {"label": "Simple Weapons",    "tags": ["weapon", "simple"],        "count": (2, 4),  "qty": (1, 3)},
            {"label": "Tools",             "tags": ["tool"],                    "count": (1, 3),  "qty": (1, 3)},
            {"label": "Healing Potions",   "tags": ["potion", "common"],        "count": (1, 2),  "qty": (1, 4)},
        ],
    },
    "blacksmith": {
        "name": "Blacksmith",
        "slots": [
            {"label": "Martial Weapons",   "tags": ["weapon", "martial"],       "count": (3, 6),  "qty": (1, 2)},
            {"label": "Simple Weapons",    "tags": ["weapon", "simple"],        "count": (2, 4),  "qty": (1, 3)},
            {"label": "Armor",             "tags": ["armor"],                   "count": (3, 5),  "qty": (1, 2)},
            {"label": "Ammunition",        "tags": ["ammunition"],              "count": (1, 3),  "qty": (10, 40)},
        ],
    },
    "apothecary": {
        "name": "Apothecary",
        "slots": [
            {"label": "Common Potions",    "tags": ["potion", "common"],        "count": (3, 6),  "qty": (1, 6)},
            {"label": "Uncommon Potions",  "tags": ["potion", "uncommon"],      "count": (1, 3),  "qty": (1, 2)},
            {"label": "Consumables",       "tags": ["consumable"],              "count": (2, 5),  "qty": (1, 8)},
            {"label": "Supplies",          "tags": ["adventuring_gear"],        "count": (1, 3),  "qty": (2, 6)},
        ],
    },
    "magic_shop": {
        "name": "Magic Shop",
        "slots": [
            {"label": "Common Magic Items",   "tags": ["magic_item", "common"],    "count": (3, 6),  "qty": (1, 2)},
            {"label": "Uncommon Magic Items", "tags": ["magic_item", "uncommon"],  "count": (2, 4),  "qty": (1, 1)},
            {"label": "Rare Magic Items",     "tags": ["magic_item", "rare"],      "count": (0, 2),  "qty": (1, 1)},
            {"label": "Scrolls",              "tags": ["scroll"],                  "count": (2, 5),  "qty": (1, 2)},
            {"label": "Potions",              "tags": ["potion"],                  "count": (2, 4),  "qty": (1, 3)},
        ],
    },
    "trade_post": {
        "name": "Trade Post",
        "slots": [
            {"label": "Trade Goods",       "tags": ["trade_good"],              "count": (6, 12), "qty": (1, 50)},
            {"label": "Supplies",          "tags": ["adventuring_gear"],        "count": (3, 6),  "qty": (1, 10)},
            {"label": "Weapons",           "tags": ["weapon", "simple"],        "count": (1, 3),  "qty": (1, 2)},
        ],
    },
}


# ── Core functions ────────────────────────────────────────────────────────────

def filter_items(items: list[dict], tags: list[str]) -> list[dict]:
    """Return items that have ALL of the given tags."""
    required = set(tags)
    return [item for item in items if required.issubset(set(item.get("tags", [])))]


def generate_slot(items: list[dict], slot: dict, rng: random.Random) -> list[dict]:
    """
    Pick a random count of distinct items matching slot["tags"],
    each with a random qty. Returns list of {"item": dict, "quantity": int}.
    """
    candidates = filter_items(items, slot["tags"])
    if not candidates:
        return []

    count_min, count_max = slot["count"]
    qty_min, qty_max = slot["qty"]

    count = rng.randint(count_min, count_max)
    count = min(count, len(candidates))

    if count == 0:
        return []

    chosen = rng.sample(candidates, count)
    return [
        {"item": item, "quantity": rng.randint(qty_min, qty_max)}
        for item in chosen
    ]


def generate_shop(
    profile_key: str,
    items: list[dict],
    seed: Optional[int] = None,
    custom_profile: Optional[dict] = None,
) -> dict:
    if seed is None:
        seed = random.randint(0, 999_999)

    rng = random.Random(seed)

    profile = custom_profile if custom_profile is not None else BUILTIN_PROFILES.get(profile_key, {})
    profile_name = profile.get("name", profile_key)

    result_slots: list[dict] = []
    all_items: list[dict] = []
    total_value = 0.0

    for slot_def in profile.get("slots", []):
        slot_items = generate_slot(items, slot_def, rng)
        result_slots.append({"label": slot_def["label"], "items": slot_items})
        for entry in slot_items:
            all_items.append(entry)
            cost_gp = entry["item"].get("cost_gp", 0.0) or 0.0
            total_value += cost_gp * entry["quantity"]

    return {
        "profile": profile_key,
        "profile_name": profile_name,
        "seed": seed,
        "slots": result_slots,
        "all_items": all_items,
        "total_value_gp": round(total_value, 2),
    }
