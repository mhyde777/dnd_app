"""Tests for lib/app/statblock_parser.py"""

import os
import pytest
from app.statblock_parser import parse_statblock, validate_statblock, statblock_key

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


# ── statblock_key tests ─────────────────────────────────────────────

class TestStatblockKey:
    def test_plain_name(self):
        assert statblock_key("Goblin") == "goblin.json"

    def test_multi_word(self):
        assert statblock_key("Ancient Red Dragon") == "ancient_red_dragon.json"

    def test_hash_suffix(self):
        assert statblock_key("Goblin #2") == "goblin.json"

    def test_number_suffix(self):
        assert statblock_key("Goblin 3") == "goblin.json"

    def test_whitespace(self):
        assert statblock_key("  Goblin  ") == "goblin.json"

    def test_special_chars(self):
        assert statblock_key("Mind Flayer (Illithid)") == "mind_flayer_illithid.json"


# ── 2014 format tests (Goblin) ─────────────────────────────────────

class TestParse2014Goblin:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = parse_statblock(_load_fixture("goblin_2014.txt"))

    def test_name(self):
        assert self.data["name"] == "Goblin"

    def test_size_type_alignment(self):
        assert self.data["size"] == "Small"
        assert self.data["type"] == "Humanoid (Goblinoid)"
        assert self.data["alignment"] == "Neutral Evil"

    def test_ac(self):
        assert self.data["armor_class"][0]["value"] == 15
        assert self.data["armor_class"][0]["source"] == "leather armor, shield"

    def test_hp(self):
        assert self.data["hit_points"]["average"] == 7
        assert self.data["hit_points"]["dice"] == "2d6"

    def test_speed(self):
        assert self.data["speed"]["walk"] == 30
        assert self.data["speed"]["fly"] is None

    def test_ability_scores(self):
        assert self.data["ability_scores"]["str"] == 8
        assert self.data["ability_scores"]["dex"] == 14
        assert self.data["ability_scores"]["con"] == 10
        assert self.data["ability_scores"]["int"] == 10
        assert self.data["ability_scores"]["wis"] == 8
        assert self.data["ability_scores"]["cha"] == 8

    def test_skills(self):
        assert self.data["skills"]["stealth"] == 6

    def test_senses(self):
        assert self.data["senses"]["darkvision"] == 60
        assert self.data["senses"]["passive_perception"] == 9

    def test_languages(self):
        assert "Common" in self.data["languages"]
        assert "Goblin" in self.data["languages"]

    def test_cr(self):
        assert self.data["challenge_rating"] == "1/4"
        assert self.data["xp"] == 50
        assert self.data["proficiency_bonus"] == 2

    def test_initiative(self):
        # 2014 D&D Beyond has "Roll Initiative! +2"
        assert self.data["initiative_bonus"] == 2

    def test_traits(self):
        assert len(self.data["special_traits"]) == 1
        assert self.data["special_traits"][0]["name"] == "Nimble Escape"

    def test_actions(self):
        assert len(self.data["actions"]) == 2
        names = [a["name"] for a in self.data["actions"]]
        assert "Scimitar" in names
        assert "Shortbow" in names

    def test_no_spellcasting(self):
        assert self.data["spellcasting"] is None


# ── 2024 format tests (Goblin Minion) ──────────────────────────────

class TestParse2024Goblin:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = parse_statblock(_load_fixture("goblin_2024.txt"))

    def test_name(self):
        assert self.data["name"] == "Goblin Minion"

    def test_size_type_alignment(self):
        assert self.data["size"] == "Small"
        assert self.data["type"] == "Fey (Goblinoid)"
        assert self.data["alignment"] == "Chaotic Neutral"

    def test_ac(self):
        assert self.data["armor_class"][0]["value"] == 12

    def test_hp(self):
        assert self.data["hit_points"]["average"] == 7

    def test_initiative(self):
        assert self.data["initiative_bonus"] == 2

    def test_cr(self):
        assert self.data["challenge_rating"] == "1/8"
        assert self.data["xp"] == 25
        assert self.data["proficiency_bonus"] == 2

    def test_ability_scores(self):
        assert self.data["ability_scores"]["str"] == 8
        assert self.data["ability_scores"]["dex"] == 15
        assert self.data["ability_scores"]["con"] == 10

    def test_senses(self):
        assert self.data["senses"]["darkvision"] == 60
        assert self.data["senses"]["passive_perception"] == 9

    def test_actions(self):
        assert len(self.data["actions"]) >= 1
        names = [a["name"] for a in self.data["actions"]]
        assert "Dagger" in names

    def test_bonus_actions(self):
        assert len(self.data["bonus_actions"]) == 1
        assert self.data["bonus_actions"][0]["name"] == "Nimble Escape"


# ── Spellcaster test (Mage, 2024) ──────────────────────────────────

class TestParseMage2024:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = parse_statblock(_load_fixture("mage_2024.txt"))

    def test_name(self):
        assert self.data["name"] == "Mage"

    def test_size_type(self):
        # "Medium Or Small Humanoid (Wizard), Neutral"
        assert self.data["type"] == "Humanoid (Wizard)"
        assert self.data["alignment"] == "Neutral"

    def test_ac_and_initiative(self):
        assert self.data["armor_class"][0]["value"] == 15
        assert self.data["initiative_bonus"] == 2

    def test_hp(self):
        assert self.data["hit_points"]["average"] == 81

    def test_cr(self):
        assert self.data["challenge_rating"] == "6"
        assert self.data["xp"] == 2300
        assert self.data["proficiency_bonus"] == 3

    def test_ability_scores(self):
        assert self.data["ability_scores"]["str"] == 9
        assert self.data["ability_scores"]["int"] == 17
        assert self.data["ability_scores"]["dex"] == 14

    def test_spellcasting_detected(self):
        assert self.data["spellcasting"] is not None

    def test_spellcasting_ability_2024_wording(self):
        # 2024: "using Intelligence as the spellcasting ability"
        assert self.data["spellcasting"]["ability"] == "Intelligence"

    def test_spellcasting_dc(self):
        assert self.data["spellcasting"]["save_dc"] == 14

    def test_spellcasting_no_attack_bonus(self):
        # 2024 mage doesn't list spell attack bonus
        assert self.data["spellcasting"]["attack_bonus"] is None

    def test_spellcasting_no_slots(self):
        # 2024 uses innate-style, no slot-based spells
        assert self.data["spellcasting"]["slots"] == {}

    def test_innate_at_will(self):
        at_will = self.data["spellcasting"]["innate"].get("at_will", [])
        assert "detect magic" in at_will
        assert "light" in at_will
        assert "prestidigitation" in at_will

    def test_innate_2_per_day(self):
        spells = self.data["spellcasting"]["innate"].get("2_per_day", [])
        assert any("fireball" in s for s in spells)
        assert "invisibility" in spells

    def test_innate_1_per_day(self):
        spells = self.data["spellcasting"]["innate"].get("1_per_day", [])
        assert "cone of cold" in spells
        assert "fly" in spells

    def test_actions(self):
        names = [a["name"] for a in self.data["actions"]]
        assert "Multiattack" in names
        assert "Arcane Burst" in names
        # Spellcasting should also be listed as an action
        assert "Spellcasting" in names

    def test_bonus_actions(self):
        assert len(self.data["bonus_actions"]) >= 1
        names = [a["name"] for a in self.data["bonus_actions"]]
        assert any("Misty Step" in n for n in names)

    def test_reactions(self):
        assert len(self.data["reactions"]) >= 1
        names = [a["name"] for a in self.data["reactions"]]
        assert any("Protective Magic" in n for n in names)


# ── Spellcaster test (Mage, 2014) ──────────────────────────────────

class TestParseMage:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = parse_statblock(_load_fixture("mage_2014.txt"))

    def test_name(self):
        assert self.data["name"] == "Mage"

    def test_saving_throws(self):
        assert self.data["saving_throws"]["int"] == 6
        assert self.data["saving_throws"]["wis"] == 4

    def test_spellcasting_detected(self):
        assert self.data["spellcasting"] is not None

    def test_spellcasting_ability(self):
        assert self.data["spellcasting"]["ability"] == "Intelligence"

    def test_spellcasting_dc(self):
        assert self.data["spellcasting"]["save_dc"] == 14

    def test_spellcasting_attack_bonus(self):
        assert self.data["spellcasting"]["attack_bonus"] == 6

    def test_spellcasting_cantrips(self):
        cantrips = self.data["spellcasting"]["spells_by_level"].get("cantrips", [])
        assert "fire bolt" in cantrips
        assert "mage hand" in cantrips

    def test_spellcasting_slots(self):
        slots = self.data["spellcasting"]["slots"]
        assert slots.get("1") == 4
        assert slots.get("2") == 3
        assert slots.get("5") == 1

    def test_spellcasting_spell_lists(self):
        spells = self.data["spellcasting"]["spells_by_level"]
        assert "shield" in spells.get("1", [])
        assert "fireball" in spells.get("3", [])
        assert "cone of cold" in spells.get("5", [])


# ── Legendary creature test (Adult Red Dragon) ─────────────────────

class TestParseAdultRedDragon:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = parse_statblock(_load_fixture("adult_red_dragon_2014.txt"))

    def test_name(self):
        assert self.data["name"] == "Adult Red Dragon"

    def test_size(self):
        assert self.data["size"] == "Huge"

    def test_speed_multiple(self):
        assert self.data["speed"]["walk"] == 40
        assert self.data["speed"]["climb"] == 40
        assert self.data["speed"]["fly"] == 80

    def test_ability_scores(self):
        assert self.data["ability_scores"]["str"] == 27
        assert self.data["ability_scores"]["dex"] == 10
        assert self.data["ability_scores"]["con"] == 25

    def test_saving_throws(self):
        assert self.data["saving_throws"]["dex"] == 6
        assert self.data["saving_throws"]["con"] == 13

    def test_damage_immunities(self):
        assert "Fire" in self.data["damage_immunities"]

    def test_cr(self):
        assert self.data["challenge_rating"] == "17"
        assert self.data["xp"] == 18000

    def test_traits(self):
        assert any(
            "Legendary Resistance" in t["name"]
            for t in self.data["special_traits"]
        )

    def test_actions(self):
        names = [a["name"] for a in self.data["actions"]]
        assert "Multiattack" in names
        assert "Bite" in names
        # em dash in "Recharge 5–6"
        assert any("Fire Breath" in n for n in names)

    def test_legendary_actions(self):
        assert self.data["legendary_actions"] is not None
        assert len(self.data["legendary_actions"]) == 3

    def test_legendary_action_count(self):
        assert self.data["legendary_action_count"] == 3

    def test_legendary_detect(self):
        detect = next(
            a for a in self.data["legendary_actions"] if a["name"] == "Detect"
        )
        assert detect["cost"] == 1

    def test_legendary_wing_attack_cost(self):
        wing = next(
            a for a in self.data["legendary_actions"]
            if "Wing Attack" in a["name"]
        )
        assert wing["cost"] == 2


# ── Validation tests ────────────────────────────────────────────────

class TestValidation:
    def test_valid_statblock_no_warnings(self):
        data = parse_statblock(_load_fixture("goblin_2014.txt"))
        warnings = validate_statblock(data)
        assert len(warnings) == 0

    def test_empty_gives_warnings(self):
        warnings = validate_statblock({})
        assert len(warnings) > 0

    def test_missing_name(self):
        data = parse_statblock(_load_fixture("goblin_2014.txt"))
        data["name"] = ""
        warnings = validate_statblock(data)
        assert any("Name" in w for w in warnings)

    def test_zero_hp_warning(self):
        data = {
            "name": "Test", "size": "Medium", "type": "Humanoid",
            "armor_class": [{"value": 10}],
            "hit_points": {"average": 0},
            "ability_scores": {
                "str": 12, "dex": 10, "con": 10,
                "int": 10, "wis": 10, "cha": 10,
            },
        }
        warnings = validate_statblock(data)
        assert any("Hit points" in w for w in warnings)
