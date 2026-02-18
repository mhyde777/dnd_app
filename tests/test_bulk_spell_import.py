from app.bulk_spell_import import dedupe_prefer_non_legacy, parse_bulk_spells


_SAMPLE = """
2nd
Calm Emotions
Concentration
Enchantment • V, S
1 Action
1 Minute
60 ft.
(20 ft. )
CHA Save
Charmed (...)
Level
2nd
Casting Time
1 Action
Range/Area
60 ft. (20 ft. )
Components
V, S
Duration
Concentration 1 Minute
School
Enchantment
Attack/Save
CHA Save
Damage/Effect
 Charmed (...)
Each Humanoid in a 20-foot-radius Sphere centered on a point you choose within range must succeed on a Charisma saving throw.
View Details Page
Tags:
Social
1st
Charm Person
Legacy
Enchantment • V, S
1 Action
1 Hour
30 ft.
WIS Save
Charmed
Level
1st
Casting Time
1 Action
Range/Area
30 ft.
Components
V, S
Duration
1 Hour
School
Enchantment
Attack/Save
WIS Save
Damage/Effect
 Charmed
You attempt to charm a humanoid you can see within range.
View Details Page
Tags:
Control
"""


def test_parse_bulk_spells_skips_legacy_by_default():
    spells = parse_bulk_spells(_SAMPLE)
    assert [s.name for s in spells] == ["Calm Emotions"]
    assert spells[0].data["concentration"] is True


def test_parse_bulk_spells_include_legacy():
    spells = parse_bulk_spells(_SAMPLE, include_legacy=True)
    names = [s.name for s in spells]
    assert "Calm Emotions" in names
    assert "Charm Person" in names


def test_dedupe_prefers_non_legacy():
    spells = parse_bulk_spells(_SAMPLE, include_legacy=True)
    # manufacture duplicate key by appending a second legacy/non-legacy pair
    keep = dedupe_prefer_non_legacy(spells + spells)
    keys = [s.key for s in keep]
    assert len(keys) == len(set(keys))
