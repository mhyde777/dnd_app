"""D&D Beyond's magic-item listing is a second paste format.

It has no cost or weight, puts rarity and type on their own header lines, and
— the part that matters most here — shows items you have not bought with a
"purchase the book" blurb where the description belongs. Those carry nothing
worth importing and must be skipped, not imported empty.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app.bulk_item_import import (  # noqa: E402
    is_magic_item_listing,
    parse_bulk_items,
    parse_bulk_items_report,
)
from app.item_parser import _normalize  # noqa: E402

OWNED = """\
Acheron Blade
Rare
Weapon
Required
Bonus: Magic, Bonus: Temporary Hit Points
Weapon (any sword), rare (requires attunement)
The black blade of this sword is crafted from a mysterious arcane alloy.

Dark Blessing. While holding the sword, you gain temporary hit points.

Notes: Bonus: Magic, Bonus: Temporary Hit Points
View Details Page
Explorer's Guide to Wildemount
Partnered Content
"""

UNOWNED = """\
Abracadabrus
Very Rare
Wondrous Item
——
Utility, Container
Icewind Dale: Rime of the Frostmaiden
This magic item is part of the Icewind Dale: Rime of the Frostmaiden book. \
You can unlock this magic item by purchasing the book in our marketplace.

View Marketplace
"""

COMMON_RING = """\
Adventurer's Ring
Common
Ring
——
Ring, common
While the cover on this ring is open, the ring produces a flame.

View Details Page
Tags:
Utility
Forgotten Realms: Heroes of Faerun
"""


def _one(text):
    items = parse_bulk_items(text)
    assert len(items) == 1, [i.name for i in items]
    return items[0]


def test_listing_is_detected_and_not_confused_with_the_equipment_format():
    lines = [l for l in _normalize(OWNED).splitlines() if l.strip()]
    assert is_magic_item_listing(lines)

    equipment = [
        "Longsword", "Martial Melee Weapon", "15 GP", "3 lb",
        "A sword.", "View Details Page", "Basic Rules (2014)",
    ]
    assert not is_magic_item_listing(equipment)


def test_owned_item_keeps_rarity_subtype_and_attunement():
    item = _one(OWNED)
    data = item.data
    assert data["name"] == "Acheron Blade"
    assert data["item_type"] == "weapon"
    assert data["subtype"] == "any sword"
    assert data["rarity"] == "rare"
    assert data["requires_attunement"] is True
    assert data["source"] == "Explorer's Guide to Wildemount"
    assert "magic_item" in data["tags"]
    # The header noise and the repeated "Notes:" line are not prose.
    assert data["description"].startswith("The black blade")
    assert "Notes:" not in data["description"]
    assert "Bonus: Magic" not in data["description"]


def test_unowned_items_are_skipped_and_named():
    items, unowned = parse_bulk_items_report(UNOWNED)
    assert items == []
    assert unowned == ["Abracadabrus"]


def test_a_mixed_paste_imports_only_what_you_own():
    items, unowned = parse_bulk_items_report(OWNED + UNOWNED + COMMON_RING)
    assert [i.name for i in items] == ["Acheron Blade", "Adventurer's Ring"]
    assert unowned == ["Abracadabrus"]


def test_common_items_are_still_tagged_as_magic_items():
    # _build_tags only infers magic_item from an uncommon-or-better rarity, but
    # everything in this listing is a magic item -- and the Magic Shop's common
    # slot matches on the tag.
    data = _one(COMMON_RING).data
    assert data["rarity"] == "common"
    assert "magic_item" in data["tags"]
    assert "common" in data["tags"]


def test_attunement_restriction_survives():
    text = OWNED.replace(
        "rare (requires attunement)",
        "rare (requires attunement by a Druid, Sorcerer, or Wizard)",
    )
    assert _one(text).data["requires_attunement"] == "by a druid, sorcerer, or wizard"
