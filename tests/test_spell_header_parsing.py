"""The spell header: level, school, name, and the two labels that hold tags.

D&D Beyond has two ways of presenting a spell, and its *detail* page keeps the
title outside the region a copy picks up while running the level and school
together — "2nd LevelConjuration". That matched no level pattern, so it was
taken as the spell's name and a spell by that name reached the library.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app.spell_parser import parse_spell, validate_spell


def _spell(header: str) -> dict:
    return parse_spell(
        f"{header}\n"
        "Casting Time: 1 hour or Ritual\n"
        "Range: 10 feet\n"
        "Duration: Instantaneous\n"
        "\n"
        "You summon a special homunculus."
    )


def test_level_school_run_together():
    d = _spell("2nd LevelConjuration")
    assert (d["level"], d["school"]) == (2, "Conjuration")


def test_level_school_with_separator():
    assert _spell("2nd-level conjuration")["level"] == 2
    assert _spell("Level 2 Conjuration (Artificer)")["school"] == "Conjuration"


def test_a_header_line_is_never_taken_as_the_name():
    d = _spell("2nd LevelConjuration")
    assert d["name"] == ""
    assert "Missing spell name" in validate_spell(d)


def test_name_line_is_kept_when_present():
    d = parse_spell(
        "Homunculus Servant\n"
        "Level 2 Conjuration (Artificer)\n"
        "Casting Time: 1 hour or Ritual\n"
        "Range: 10 feet\n"
        "Duration: Instantaneous\n"
        "\n"
        "You summon a special homunculus."
    )
    assert d["name"] == "Homunculus Servant"
    assert (d["level"], d["school"]) == (2, "Conjuration")
    assert d["description"].startswith("You summon")


def test_a_level_line_needs_a_real_school():
    """"Level 2 spell slots or higher" must not parse as 2nd-level Spell."""
    d = _spell("Level 2 spell slots or higher")
    assert d["school"] == ""
    assert d["name"] == "Level 2 spell slots or higher"


# ── card format: labels emitted with no value ─────────────────────────────────

def _card(effect_line: str) -> dict:
    return parse_spell(
        "Homunculus Servant\n"
        "Level\n2nd\n"
        "Casting Time\n1 Hour\n"
        "Range/Area\n10 ft.\n"
        "Components\nV, S, M\n"
        "Duration\nInstantaneous\n"
        "School\nConjuration\n"
        "Attack/Save\nNone\n"
        "Damage/Effect\n"
        f"{effect_line}\n"
    )


def test_a_short_tag_is_taken_as_the_damage_effect():
    assert _card("Cold (...)")["damage_effect"] == "Cold (...)"


def test_prose_after_an_empty_label_stays_in_the_description():
    """D&D Beyond emits "Damage/Effect" even with nothing to put under it."""
    prose = "You summon a special homunculus in an unoccupied space within range."
    d = _card(prose)
    assert d["damage_effect"] == ""
    assert d["description"].startswith("You summon")
    assert "Damage/Effect" not in d["description"]
