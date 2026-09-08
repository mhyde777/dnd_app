# app/spell_parser.py
"""
Parse D&D Beyond spell text into a structured dict.

Handles two paste formats:
  - Card format:   label and value on separate lines (current D&D Beyond website)
  - Inline format: "Label: Value" on the same line (older exports / manual text)

Entry points:
    parse_spell(text: str) -> dict
    validate_spell(data: dict) -> list[str]
    spell_key(name: str) -> str

Output schema:
    name, level (int), school, casting_time, range, components,
    duration, concentration (bool), attack_save, damage_effect,
    description, footnotes (list[str])
"""
from __future__ import annotations

import re

from app.text_blocks import SourceLine, join_paragraphs, raw_slice, split_lines


# ── Key helper ────────────────────────────────────────────────────────────────

def spell_key(name: str) -> str:
    """Convert a spell name to its storage key.

    'Fireball'                 → 'fireball.json'
    'Magic Missile'            → 'magic_missile.json'
    "Tasha's Hideous Laughter" → 'tashas_hideous_laughter.json'
    """
    key = name.strip().lower()
    key = key.replace("'", "").replace("’", "")  # strip apostrophes before slugifying
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return f"{key}.json"


# ── Card-format label map ─────────────────────────────────────────────────────
# Maps lowercased label text → result dict key

_CARD_LABEL_MAP: dict[str, str] = {
    "level":         "level_str",
    "casting time":  "casting_time",
    "range/area":    "range",
    "range":         "range",
    "components":    "components",
    "duration":      "duration",
    "school":        "school",
    "attack/save":   "attack_save",
    "damage/effect": "damage_effect",
    "damage/type":   "damage_effect",
}

_CARD_KNOWN_LABELS = set(_CARD_LABEL_MAP.keys())

# Header lines that appear above the name in a card paste, or beside it
_LEVEL_TOKEN_RE = re.compile(r'^(?:cantrip|\d+(?:st|nd|rd|th))$', re.IGNORECASE)
_HEADER_NOISE = {"concentration", "legacy", "ritual"}

# Trailing site furniture D&D Beyond includes in a card copy
_CARD_END_MARKERS = {"view details page", "tags:", "available for:"}

# "Attack/Save" and "Damage/Effect" are the last two labels of a card copy, and
# D&D Beyond emits the label even when the spell has no value for it -- so the
# line after it is the opening paragraph of the description, not a value. Real
# values are short tags ("None", "DEX Save", "Cold (...)"): the 95th percentile
# is 17 characters and none is a sentence. Without this the first paragraph of
# 19 spells, Homunculus Servant among them, vanished into damage_effect.
_CARD_TAG_FIELDS = frozenset({"attack_save", "damage_effect"})
_CARD_TAG_MAX = 70


def _is_card_tag(field: str, value: str) -> bool:
    """True when the line after a label really is that label's value."""
    if field not in _CARD_TAG_FIELDS:
        return True
    value = value.strip()
    if not value or len(value) > _CARD_TAG_MAX:
        return False
    return not value.endswith((".", "!", "?"))

# Inline-format "Label: value" patterns
_INLINE_LABEL_PATTERNS = [
    (re.compile(r'^casting\s*time\s*[:\u2014]\s*(.+)$', re.IGNORECASE), "casting_time"),
    (re.compile(r'^range(?:/area)?\s*[:\u2014]\s*(.+)$', re.IGNORECASE), "range"),
    (re.compile(r'^components?\s*[:\u2014]\s*(.+)$', re.IGNORECASE), "components"),
    (re.compile(r'^duration\s*[:\u2014]\s*(.+)$', re.IGNORECASE), "duration"),
    (re.compile(r'^school\s*[:\u2014]\s*(.+)$', re.IGNORECASE), "school"),
    (re.compile(r'^attack/save\s*[:\u2014]\s*(.+)$', re.IGNORECASE), "attack_save"),
    (re.compile(r'^damage(?:/effect|/type)?\s*[:\u2014]\s*(.+)$', re.IGNORECASE), "damage_effect"),
]

# The eight schools. A level line is only accepted when its second half names
# one, so "Level 2 spell slots or higher" cannot pose as "2nd-level Slots".
_SCHOOLS = frozenset({
    "abjuration", "conjuration", "divination", "enchantment",
    "evocation", "illusion", "necromancy", "transmutation",
})

# Level-line patterns for inline format. The separator between "level" and the
# school is optional throughout: D&D Beyond's spell *detail* page renders the
# two in adjacent elements, and copying it yields them run together --
# "2nd LevelConjuration" -- which used to match nothing and be taken as the
# spell's name.
_LEVEL_LINE_PATTERNS = [
    (re.compile(r'^level\s*(\d+)\s*([A-Za-z]+)', re.IGNORECASE), "level_school"),
    (re.compile(r'^(\d+)(?:st|nd|rd|th)[-\s]*level\s*([A-Za-z]+)', re.IGNORECASE), "level_school"),
    (re.compile(r'^([A-Za-z]+)\s*cantrip', re.IGNORECASE), "school_cantrip"),
    (re.compile(r'^cantrip$', re.IGNORECASE), "cantrip"),
]


def _match_level_line(line: str) -> tuple[str, re.Match] | None:
    """The level-line pattern this line matches, if its school is a real one."""
    for pattern, kind in _LEVEL_LINE_PATTERNS:
        m = pattern.match(line)
        if not m:
            continue
        if kind == "level_school" and m.group(2).lower() not in _SCHOOLS:
            continue
        if kind == "school_cantrip" and m.group(1).lower() not in _SCHOOLS:
            continue
        return kind, m
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text


def _empty_result() -> dict:
    return {
        "name": "",
        "level": 0,
        "school": "",
        "casting_time": "",
        "range": "",
        "components": "",
        "duration": "",
        "concentration": False,
        "attack_save": "",
        "damage_effect": "",
        "description": "",
        "footnotes": [],
    }


def _parse_level_value(s: str) -> int:
    """'Cantrip' → 0, '1st' → 1, '3' → 3, '3rd' → 3."""
    s = s.strip().lower()
    if s in ("cantrip", "0"):
        return 0
    m = re.match(r'(\d+)', s)
    return int(m.group(1)) if m else 0


def _is_card_format(lines: list[str]) -> bool:
    """Return True if this looks like the label-per-line card paste format."""
    for line in lines[1:]:
        stripped = line.strip().lower()
        if stripped in _CARD_KNOWN_LABELS:
            return True
        # "Display Spell Card on VTT" header is a strong signal
        if re.match(r'^display\s+spell\s+card', stripped):
            return True
    return False


def _postprocess(result: dict) -> dict:
    """Shared post-processing: extract concentration from duration if present."""
    duration = result.get("duration", "")
    if re.match(r'^concentration\b', duration, re.IGNORECASE):
        result["concentration"] = True
        duration = re.sub(r'^concentration[,\s]+', '', duration, flags=re.IGNORECASE).strip()
        result["duration"] = duration
    return result


# ── Card-format parser ────────────────────────────────────────────────────────

def _find_label_block(lines: list[str]) -> int:
    """Index of the first "Label\nValue" pair, or -1.

    D&D Beyond's card copy leads with a summary header — the level badge, the
    spell name, "School • Components", then the same values again unlabelled —
    before the labelled block starts. The label block is the reliable part, so
    find it rather than assuming it begins on line 1.
    """
    for idx in range(len(lines) - 1):
        if lines[idx].strip().lower() in _CARD_LABEL_MAP:
            return idx
    return -1


def _name_from_header(header: list[str]) -> tuple[str, bool]:
    """Pick the spell name out of the summary header, and spot Concentration.

    The name is the first line that isn't a level badge ("3rd"), a standalone
    marker ("Concentration", "Legacy"), or the VTT card header.
    """
    name = ""
    concentration = False
    for line in header:
        stripped = line.strip()
        lower = stripped.lower()
        if lower == "concentration":
            concentration = True
            continue
        if lower in _HEADER_NOISE or _LEVEL_TOKEN_RE.match(stripped):
            continue
        if re.match(r'^display\s+spell\s+card', lower):
            continue
        if not name:
            name = stripped
    return name, concentration


def _parse_card_format(lines: list[SourceLine], raw: list[str]) -> dict:
    """Parse the label-per-line D&D Beyond card paste format."""
    result = _empty_result()

    label_start = _find_label_block(lines)
    if label_start < 0:
        label_start = 1

    header = lines[:label_start] or lines[:1]
    name, concentration = _name_from_header(header)
    result["name"] = name or lines[0].strip()
    if concentration:
        result["concentration"] = True

    # A level badge in the header stands in if the block has no "Level" label
    header_level = next(
        (l.strip() for l in header if _LEVEL_TOKEN_RE.match(l.strip())), ""
    )

    # Parse label / value pairs
    idx = label_start
    saw_level_label = False
    while idx < len(lines) - 1:
        label = lines[idx].strip().lower()
        if label in _CARD_LABEL_MAP:
            field = _CARD_LABEL_MAP[label]
            value = lines[idx + 1].strip()
            if not _is_card_tag(field, value):
                # The label was emitted with no value; the description starts
                # on the next line. Drop the label, keep the prose.
                idx += 1
                break
            if field == "level_str":
                result["level"] = _parse_level_value(value)
                saw_level_label = True
            else:
                result[field] = value
            idx += 2
        else:
            break   # everything after this is description / footnotes

    if not saw_level_label and header_level:
        result["level"] = _parse_level_value(header_level)

    # Remaining lines: description + footnotes, minus the site furniture
    # ("View Details Page", "Tags:" and the tag list) that trails a card copy.
    end = next(
        (i for i in range(idx, len(lines))
         if lines[i].strip().lower() in _CARD_END_MARKERS),
        len(lines),
    )

    # Cut the description out of the raw paste so its blank lines -- the
    # paragraph breaks, and what sets a table apart from the prose above it --
    # are still there. Footnotes are pulled out of that slice, not out of the
    # compacted list, for the same reason.
    footnotes: list[str] = []
    desc_lines: list[str] = []
    for line in raw_slice(raw, lines, idx, end):
        stripped = line.strip()
        if re.match(r'^\*\s*-?\s*\(', stripped):
            footnotes.append(stripped)
        else:
            desc_lines.append(line)

    result["description"] = join_paragraphs(desc_lines)
    result["footnotes"] = footnotes

    return _postprocess(result)


# ── Inline-format parser ──────────────────────────────────────────────────────

def _parse_inline_format(lines: list[SourceLine], raw: list[str]) -> dict:
    """Parse the older 'Label: Value' inline format."""
    result = _empty_result()

    # A paste that opens on its level line carries no name -- D&D Beyond's
    # detail page keeps the title outside the copied region. Taking line 0
    # regardless is how a spell called "2nd LevelConjuration" got into the
    # library; leaving it empty lets validate_spell() say so instead.
    idx = 0
    if _match_level_line(lines[0]) is None:
        result["name"] = lines[0].strip()
        idx = 1

    if idx >= len(lines):
        return result

    # Try to read a level+school line
    matched = _match_level_line(lines[idx])
    if matched is not None:
        kind, m = matched
        if kind == "level_school":
            result["level"] = int(m.group(1))
            result["school"] = m.group(2).capitalize()
        elif kind == "school_cantrip":
            result["school"] = m.group(1).capitalize()
        # cantrip: level stays 0
        idx += 1

    # Labeled property lines
    desc_start = len(lines)

    while idx < len(lines):
        line = lines[idx]
        matched = False
        for pattern, field in _INLINE_LABEL_PATTERNS:
            m = pattern.match(line)
            if m:
                if field == "school" and result["school"]:
                    matched = True
                    break
                result[field] = m.group(1).strip()
                matched = True
                break
        if not matched:
            # An unrecognised property header ("Attack/Save: ...") is a
            # short label. The length bound matters: without it, a first
            # description line whose opening clause ends in a colon --
            # "You touch a creature and remove one of the following
            # effects from it: ..." -- matches too, and the whole spell
            # description is silently dropped.
            if re.match(r'^[A-Z][A-Za-z /]{0,24}:\s*\S', line):
                pass  # unrecognised property header, skip
            else:
                desc_start = idx
                break
        idx += 1

    result["description"] = join_paragraphs(raw_slice(raw, lines, desc_start))

    return _postprocess(result)


# ── Public entry point ────────────────────────────────────────────────────────

def parse_spell(text: str) -> dict:
    """Parse D&D Beyond spell text (card or inline format) into a spell dict."""
    text = _normalize(text)
    lines, raw = split_lines(text)

    if not lines:
        raise ValueError("Empty text — nothing to parse.")

    if _is_card_format(lines):
        return _parse_card_format(lines, raw)
    return _parse_inline_format(lines, raw)


# ── Validator ─────────────────────────────────────────────────────────────────

def validate_spell(data: dict) -> list[str]:
    """Return a list of warning strings for missing or suspect fields."""
    warnings: list[str] = []
    if not data.get("name"):
        warnings.append("Missing spell name")
    if not data.get("casting_time"):
        warnings.append("Missing casting time")
    if not data.get("duration"):
        warnings.append("Missing duration")
    if not data.get("description"):
        warnings.append("Missing description")
    return warnings
