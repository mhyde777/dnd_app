"""Tables, statblocks and paragraph breaks survive the parse and the render.

A D&D Beyond paste writes tables as tab-delimited rows and paragraph breaks as
blank lines. The parsers used to drop every blank line before assembling a
description, and the card renderers turned what was left into `<br>`-joined
text, where HTML collapsed the tabs away — so a table arrived as one run-on
line per row with no separation from the prose introducing it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app.bulk_item_import import parse_bulk_items
from app.item_parser import parse_item
from app.spell_parser import parse_spell
from app.text_blocks import join_paragraphs, raw_slice, split_lines
from ui.rich_text import render_description


# ── text_blocks ───────────────────────────────────────────────────────────────

def test_split_lines_keeps_leading_tabs_in_raw():
    """An ability table's header opens with empty cells; stripping them slides it."""
    lines, raw = split_lines(" \t \tMod\tSave\nSTR\t16\t+3\t+3\n")
    assert lines[0] == "Mod\tSave"          # compacted view stays fully stripped
    assert raw[0].split("\t") == ["", " ", "Mod", "Save"]
    assert lines[1].index == 1


def test_raw_slice_recovers_blank_lines():
    lines, raw = split_lines("Name\n\nFirst para\n\nSecond para\n")
    assert raw_slice(raw, lines, 1) == ["First para", "", "Second para"]


def test_join_paragraphs_collapses_blank_runs():
    assert join_paragraphs(["a", "", "", "b", ""]) == "a\n\nb"


# ── parsers ───────────────────────────────────────────────────────────────────

_ITEM = """Widget of Testing
Wondrous Item, rare

An opening paragraph.

Roll on the table:

1d4\tEffect
1\tNothing happens.
2\tSomething happens.
"""


def test_parse_item_keeps_paragraphs_and_table():
    data = parse_item(_ITEM)
    assert "\n\n" in data["description"]
    assert "1d4\tEffect" in data["description"]
    assert "\n1\tNothing happens." in data["description"]


def test_parse_spell_keeps_paragraphs_and_table():
    text = (
        "Control Testing\n"
        "3rd-level transmutation\n"
        "Casting Time: 1 minute\n"
        "Range: Self\n"
        "Components: V, S\n"
        "Duration: 8 hours\n"
        "\n"
        "You take control of the weather.\n"
        "\n"
        "Stage\tCondition\n"
        "1\tClear\n"
        "2\tOvercast\n"
    )
    data = parse_spell(text)
    assert "You take control of the weather.\n\nStage\tCondition" in data["description"]


def test_bulk_magic_item_keeps_paragraphs_and_table():
    text = (
        "Bag of Testing\n"
        "Rare\n"
        "Wondrous Item\n"
        "——\n"
        "Wondrous Item, rare\n"
        "This bag holds beans.\n"
        "\n"
        "Plant one and roll:\n"
        "\n"
        "1d4\tEffect\n"
        "1\tA geyser erupts.\n"
        "2\tA treant sprouts.\n"
        "View Details Page\n"
        "Dungeon Master's Guide\n"
    )
    items = parse_bulk_items(text)
    assert len(items) == 1
    desc = items[0].data["description"]
    assert "This bag holds beans.\n\nPlant one and roll:\n\n1d4\tEffect" in desc
    assert desc.endswith("2\tA treant sprouts.")


# ── renderer ──────────────────────────────────────────────────────────────────

def test_render_builds_a_real_table():
    html = render_description("Roll:\n\n1d4\tEffect\n1\tNothing\n2\tSomething")
    assert "<table" in html and html.count("<tr") == 3
    assert "<th" in html and ">1d4<" in html
    # The prose above the table is its own paragraph, not a row of it.
    assert html.index("Roll:") < html.index("<table")


def test_render_pads_ragged_rows():
    html = render_description("A\tB\tC\n1\t2")
    assert html.count("<td") == 3


def test_render_leaves_a_lone_tabbed_line_as_prose():
    """One tabbed line is a stray tab in a sentence, not a one-row table."""
    html = render_description("A sentence\twith a stray tab.")
    assert "<table" not in html
    assert "A sentence\u2003with a stray tab." in html  # em space, not collapsed


def test_render_escapes_html():
    html = render_description("Crawly & Rolly <not a tag>")
    assert "&amp;" in html and "&lt;not a tag&gt;" in html


def test_render_bolds_statblock_labels():
    html = render_description("Armor Class: 20\nHit Points: 200")
    assert "<b style=\"color:#7A1F1F;\">Armor Class</b> 20" in html


def test_render_bolds_trait_lead_in():
    html = render_description("Fire Resistance. You have resistance to fire damage.")
    assert "<b style=\"color:#7A1F1F;\">Fire Resistance.</b>" in html


def test_render_leaves_ordinary_prose_alone():
    """The trait pattern must not fire on a normal sentence."""
    text = "It has 1d10 + 20 fruit. The tree vanishes after 1 hour."
    assert "<b" not in render_description(text)


def test_render_empty_description():
    assert render_description("") == ""


# ── merged ability tables ─────────────────────────────────────────────────────

_ABILITY_BLOCK = (
    "\t \tMod\tSave\n"
    "STR\t4\t-3\t-3\n"
    "DEX\t15\t+2\t+2\n"
    "CON\t12\t+1\t+1\n"
    "\t \tMod\tSave\n"
    "INT\t10\t+0\t+0\n"
    "WIS\t10\t+0\t+0\n"
    "CHA\t7\t-2\t-2"
)


def test_repeated_header_row_is_dropped():
    """D&D Beyond splits an ability block into two groups, each with a header."""
    html = render_description(_ABILITY_BLOCK)
    assert html.count("<table") == 1
    assert html.count(">Mod<") == 1          # the repeat is furniture, not data
    assert html.count("<tr") == 7            # header + six abilities


def test_ability_table_gets_a_score_column_label():
    html = render_description(_ABILITY_BLOCK)
    assert ">Score<" in html


def test_table_rows_are_striped():
    html = render_description("A\tB\n1\tx\n2\ty\n3\tz")
    assert html.count("bgcolor=") == 2       # header + one striped body row


# ── table titles ──────────────────────────────────────────────────────────────

def test_short_line_above_a_table_becomes_its_title():
    html = render_description("Precipitation\nStage\tCondition\n1\tClear")
    assert html.index("Precipitation") < html.index("<table")
    assert "<p" in html.split("Precipitation")[0][-80:]


def test_a_sentence_above_a_table_stays_prose():
    text = "Roll on the following table to determine the effect.\n1d4\tEffect\n1\tNothing"
    html = render_description(text)
    assert "determine the effect." in html


# ── statblocks ────────────────────────────────────────────────────────────────

_STATBLOCK = (
    "You summon a homunculus.\n"
    "\n"
    "Homunculus Servant\n"
    "Tiny Construct, Neutral\n"
    "\n"
    "AC 13\n"
    "\n"
    "HP 5 + 5 per spell level\n"
    "\n"
    "Traits\n"
    "\n"
    "Evasion. It takes no damage on a successful save."
)


def test_statblock_is_rendered_as_its_own_panel():
    html = render_description(_STATBLOCK)
    # The prose above it is outside the panel.
    assert html.index("You summon a homunculus.") < html.index("Homunculus Servant")
    assert "bgcolor=\"#F9F0DC\"" in html
    assert "Tiny Construct, Neutral" in html


def test_bare_statblock_labels_are_bolded_inside_a_statblock():
    html = render_description(_STATBLOCK)
    assert "<b style=\"color:#7A1F1F;\">AC</b> 13" in html
    assert "<b style=\"color:#7A1F1F;\">HP</b> 5 + 5 per spell level" in html


def test_section_headings_are_rendered_as_headings():
    html = render_description(_STATBLOCK)
    assert "border-bottom:1px solid #C9801A;\">Traits</p>" in html


def test_bare_labels_stay_plain_outside_a_statblock():
    """"Speed" can open an ordinary sentence; only the colon form is safe."""
    html = render_description("Speed is doubled while you wear the boots.")
    assert "<b" not in html


def test_a_description_opening_on_a_size_word_is_not_a_statblock():
    """An item describing itself as "Large object …" introduces no creature."""
    html = render_description("Large object with the following statistics.\n\nAC 20")
    assert "bgcolor=\"#F9F0DC\"" not in html


def test_a_sentence_shaped_like_a_lead_in_is_not_bolded():
    """"The apparatus floats on water. It can also…" is prose, not a trait."""
    text = "The apparatus floats on water. It can also go underwater 900 feet."
    assert "<b" not in render_description(text)


def test_title_case_lead_ins_still_bold():
    for lead in ("Fire Resistance", "Blend with the Blaze", "Using a Higher-Level Spell Slot"):
        html = render_description(f"{lead}. As an action, you do the thing.")
        assert f">{lead}.</b>" in html, lead
