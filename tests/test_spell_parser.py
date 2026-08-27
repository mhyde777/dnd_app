from app.spell_parser import parse_spell, validate_spell


# A single-spell copy from the current D&D Beyond spell page: the summary
# header (level badge, name, "School • Components", then the same values
# unlabelled) comes before the labelled block.
_CARD_WITH_HEADER = """
3rd
Nondetection
Abjuration • V, S, M
1 Action
8 Hours
Touch
Deception
Level
3rd
Casting Time
1 Action
Range/Area
Touch
Components
V, S, M *
Duration
8 Hours
School
Abjuration
Attack/Save
None
Damage/Effect
Deception
For the duration, you hide a target that you touch from Divination spells.

* - (a pinch of diamond dust worth 25+ GP, which the spell consumes)
View Details Page
Tags:
Deception
"""

_CARD_NAME_FIRST = """
Nondetection
Level
3rd
Casting Time
1 Action
Range/Area
Touch
Components
V, S, M *
Duration
8 Hours
School
Abjuration
For the duration, you hide a target that you touch from Divination spells.
"""

_CARD_CONCENTRATION = """
2nd
Calm Emotions
Concentration
Enchantment • V, S
Level
2nd
Casting Time
1 Action
Range/Area
60 ft. (20 ft.)
Components
V, S
Duration
Concentration 1 Minute
School
Enchantment
Each Humanoid in a 20-foot-radius Sphere must succeed on a Charisma saving throw.
"""

_INLINE = """
Fireball
3rd-level Evocation
Casting Time: 1 Action
Range: 150 feet
Components: V, S, M (a tiny ball of bat guano and sulfur)
Duration: Instantaneous
A bright streak flashes from your pointing finger.
"""


def test_card_with_summary_header():
    data = parse_spell(_CARD_WITH_HEADER)
    assert data["name"] == "Nondetection"
    assert data["level"] == 3
    assert data["school"] == "Abjuration"
    assert data["casting_time"] == "1 Action"
    assert data["range"] == "Touch"
    assert data["components"] == "V, S, M *"
    assert data["duration"] == "8 Hours"
    assert data["attack_save"] == "None"
    assert data["damage_effect"] == "Deception"
    assert validate_spell(data) == []


def test_card_header_footnote_and_trailing_metadata():
    data = parse_spell(_CARD_WITH_HEADER)
    assert data["footnotes"] == [
        "* - (a pinch of diamond dust worth 25+ GP, which the spell consumes)"
    ]
    assert data["description"].startswith("For the duration")
    # "View Details Page" / "Tags:" / the tag list are site furniture
    assert "View Details Page" not in data["description"]
    assert "Tags:" not in data["description"]


def test_card_without_summary_header_still_parses():
    data = parse_spell(_CARD_NAME_FIRST)
    assert data["name"] == "Nondetection"
    assert data["level"] == 3
    assert data["casting_time"] == "1 Action"
    assert data["duration"] == "8 Hours"


def test_card_header_concentration_marker():
    data = parse_spell(_CARD_CONCENTRATION)
    assert data["name"] == "Calm Emotions"
    assert data["level"] == 2
    assert data["concentration"] is True
    assert data["duration"] == "1 Minute"


def test_inline_format_unaffected():
    data = parse_spell(_INLINE)
    assert data["name"] == "Fireball"
    assert data["level"] == 3
    assert data["school"] == "Evocation"
    assert data["casting_time"] == "1 Action"
    assert data["range"] == "150 feet"
    assert data["duration"] == "Instantaneous"
