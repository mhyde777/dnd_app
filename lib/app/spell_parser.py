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

# Level-line patterns for inline format
_LEVEL_LINE_PATTERNS = [
    (re.compile(r'^level\s+(\d+)\s+(\w+)', re.IGNORECASE), "level_school"),
    (re.compile(r'^(\d+)(?:st|nd|rd|th)[- ]level\s+(\w+)', re.IGNORECASE), "level_school"),
    (re.compile(r'^(\w+)\s+cantrip', re.IGNORECASE), "school_cantrip"),
    (re.compile(r'^cantrip$', re.IGNORECASE), "cantrip"),
]


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


def _parse_card_format(lines: list[str]) -> dict:
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
    desc_lines: list[str] = []
    footnotes: list[str] = []

    for line in lines[idx:]:
        stripped = line.strip()
        if stripped.lower() in _CARD_END_MARKERS:
            break
        # Component footnote: "* (a pinch...)" or "* - (a pinch...)"
        if re.match(r'^\*\s*-?\s*\(', stripped):
            footnotes.append(stripped)
        else:
            desc_lines.append(line)

    result["description"] = "\n\n".join(
        para.strip()
        for para in "\n".join(desc_lines).split("\n\n")
        if para.strip()
    )
    result["footnotes"] = footnotes

    return _postprocess(result)


# ── Inline-format parser ──────────────────────────────────────────────────────

def _parse_inline_format(lines: list[str]) -> dict:
    """Parse the older 'Label: Value' inline format."""
    result = _empty_result()
    result["name"] = lines[0].strip()

    idx = 1
    if idx >= len(lines):
        return result

    # Try to read a level+school line
    level_line = lines[idx]
    for pattern, kind in _LEVEL_LINE_PATTERNS:
        m = pattern.match(level_line)
        if m:
            if kind == "level_school":
                result["level"] = int(m.group(1))
                result["school"] = m.group(2).capitalize()
            elif kind == "school_cantrip":
                result["school"] = m.group(1).capitalize()
            # cantrip: level stays 0
            idx += 1
            break

    # Labeled property lines
    desc_lines: list[str] = []
    in_description = False

    while idx < len(lines):
        line = lines[idx]
        if not in_description:
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
                if re.match(r'^[A-Z][A-Za-z /]{0,24}:\s*\S', line) and not desc_lines:
                    pass  # unrecognised property header, skip
                else:
                    in_description = True
                    desc_lines.append(line)
        else:
            desc_lines.append(line)
        idx += 1

    result["description"] = "\n\n".join(
        para.strip()
        for para in "\n".join(desc_lines).split("\n\n")
        if para.strip()
    )

    return _postprocess(result)


# ── Public entry point ────────────────────────────────────────────────────────

def parse_spell(text: str) -> dict:
    """Parse D&D Beyond spell text (card or inline format) into a spell dict."""
    text = _normalize(text)
    lines = [l.strip() for l in text.strip().splitlines()]
    lines = [l for l in lines if l]

    if not lines:
        raise ValueError("Empty text — nothing to parse.")

    if _is_card_format(lines):
        return _parse_card_format(lines)
    return _parse_inline_format(lines)


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
