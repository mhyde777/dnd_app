"""The type line is where an item's rarity and attunement come from.

Both the SRD and D&D Beyond write attunement inside the rarity's parentheses,
which the parser used to read as neither a rarity nor an attunement -- losing
both without a warning. Rarity drives the `magic_item` tag, which is what the
Shop Generator's rarity slots match on, so the loss was invisible until a shop
came up empty.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app.item_parser import _parse_type_line, parse_item  # noqa: E402


@pytest.mark.parametrize("line,expected", [
    # Attunement as its own comma-separated part -- the shape that always worked.
    ("Wondrous Item, Uncommon, Requires Attunement",
     ("wondrous_item", "", "uncommon", True)),
    ("Ring, Rare, Requires Attunement by a Spellcaster",
     ("ring", "", "rare", "by a spellcaster")),
    # Attunement in parentheses after the rarity.
    ("Wondrous Item, Uncommon (Requires Attunement)",
     ("wondrous_item", "", "uncommon", True)),
    ("Wondrous Item, Rare (Requires Attunement by a Spellcaster)",
     ("wondrous_item", "", "rare", "by a spellcaster")),
    ("Weapon (any sword), Very Rare (Requires Attunement)",
     ("weapon", "any sword", "very_rare", True)),
    # Commas inside the parenthetical belong to the attunement clause, not to
    # the type line -- splitting on them truncated this to "by a druid".
    ("Staff, Very Rare (Requires Attunement by a Druid, Sorcerer, Warlock, or Wizard)",
     ("staff", "", "very_rare", "by a druid, sorcerer, warlock, or wizard")),
    # No attunement at all.
    ("Wondrous Item, Legendary", ("wondrous_item", "", "legendary", False)),
    ("Weapon (martial, melee)", ("weapon", "martial melee", "", False)),
    ("Ammunition (+1), Uncommon", ("ammunition", "+1", "uncommon", False)),
])
def test_type_line_yields_rarity_and_attunement(line, expected):
    assert _parse_type_line(line) == expected


def test_parenthesised_attunement_still_tags_as_a_magic_item():
    # The whole point: a rarity the parser cannot see means no magic_item tag,
    # and the Magic Shop profile then matches nothing.
    data = parse_item(
        "Cloak of Displacement\n"
        "Wondrous Item, Rare (Requires Attunement)\n"
        "This cloak projects an illusion of your position."
    )
    assert data["rarity"] == "rare"
    assert data["requires_attunement"] is True
    assert "magic_item" in data["tags"]
    assert "rare" in data["tags"]
