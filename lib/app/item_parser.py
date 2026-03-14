# app/item_parser.py
from __future__ import annotations

import re


# ── Key helper ────────────────────────────────────────────────────────────────

def item_key(name: str) -> str:
    key = name.strip().lower()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return f"{key}.json"


# ── Type normalization ────────────────────────────────────────────────────────

_TYPE_MAP: dict[str, str] = {
    "weapon":           "weapon",
    "armor":            "armor",
    "potion":           "potion",
    "scroll":           "scroll",
    "wondrous item":    "wondrous_item",
    "wondrous_item":    "wondrous_item",
    "ring":             "ring",
    "rod":              "rod",
    "staff":            "staff",
    "wand":             "wand",
    "tool":             "tool",
    "ammunition":       "ammunition",
    "adventuring gear": "adventuring_gear",
    "adventuring_gear": "adventuring_gear",
    "trade good":       "trade_good",
    "trade_good":       "trade_good",
    "vehicle":          "vehicle",
    "holy symbol":      "holy_symbol",
    "holy_symbol":      "holy_symbol",
    "arcane focus":     "arcane_focus",
    "arcane_focus":     "arcane_focus",
    "gemstone":         "gemstone",
    "gem":              "gemstone",
    "explosive":        "explosive",
    "poison":           "poison",
    "food and drink":   "adventuring_gear",
    "food_and_drink":   "adventuring_gear",
    "mount":            "mount",
    "pack":             "adventuring_gear",
    "equipment pack":   "adventuring_gear",
    "equipment_pack":   "adventuring_gear",
    "tack and harness": "adventuring_gear",
    "tack, harness, and drawn vehicles": "adventuring_gear",
    "druidic focus":    "arcane_focus",
    "druidic_focus":    "arcane_focus",
    "musical instrument": "tool",
    "musical_instrument": "tool",
    "gaming set":       "tool",
    "gaming_set":       "tool",
    "artisan's tools":  "tool",
    "artisan tools":    "tool",
}

_RARITY_MAP: dict[str, str] = {
    "common":     "common",
    "uncommon":   "uncommon",
    "rare":       "rare",
    "very rare":  "very_rare",
    "very_rare":  "very_rare",
    "legendary":  "legendary",
    "artifact":   "artifact",
    "varies":     "varies",
}

_CARD_LABEL_MAP: dict[str, str] = {
    "cost":               "cost",
    "weight":             "weight",
    "properties":         "properties",
    "damage":             "damage",
    "ac":                 "ac",
    "armor class":        "ac",
    "source":             "source",
    "requires attunement": "requires_attunement",
}

_CARD_KNOWN_LABELS = set(_CARD_LABEL_MAP.keys())

_INLINE_LABEL_PATTERNS = [
    (re.compile(r'^cost\s*:\s*(.+)$', re.IGNORECASE),        "cost"),
    (re.compile(r'^weight\s*:\s*(.+)$', re.IGNORECASE),       "weight"),
    (re.compile(r'^properties\s*:\s*(.+)$', re.IGNORECASE),   "properties"),
    (re.compile(r'^damage\s*:\s*(.+)$', re.IGNORECASE),       "damage"),
    (re.compile(r'^ac\s*:\s*(.+)$', re.IGNORECASE),           "ac"),
    (re.compile(r'^armor\s+class\s*:\s*(.+)$', re.IGNORECASE), "ac"),
    (re.compile(r'^source\s*:\s*(.+)$', re.IGNORECASE),       "source"),
    (re.compile(r'^requires?\s+attunement\s*:\s*(.+)$', re.IGNORECASE), "requires_attunement"),
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
        "item_type": "other",
        "subtype": "",
        "rarity": "",
        "requires_attunement": False,
        "cost": "",
        "cost_gp": 0.0,
        "weight": 0.0,
        "properties": [],
        "damage": "",
        "ac": "",
        "description": "",
        "tags": [],
        "source": "",
    }


def _parse_cost_gp(cost_str: str) -> float:
    cost_str = cost_str.strip().lower().replace(",", "")
    m = re.search(r'([\d.]+)\s*(gp|sp|cp)', cost_str)
    if not m:
        return 0.0
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "gp":
        return value
    if unit == "sp":
        return round(value * 0.1, 4)
    if unit == "cp":
        return round(value * 0.01, 4)
    return 0.0


def _parse_weight(weight_str: str) -> float:
    m = re.search(r'([\d.]+)', weight_str)
    return float(m.group(1)) if m else 0.0


def _parse_attunement(value: str) -> bool | str:
    low = value.strip().lower()
    if not low or low == "no" or low == "false":
        return False
    if low in ("yes", "true", "required"):
        return True
    # "by a spellcaster", "by a cleric or paladin", etc.
    m = re.search(r'by\s+(.+)', low)
    if m:
        return f"by {m.group(1).strip()}"
    return True


def _parse_type_line(line: str) -> tuple[str, str, str, bool | str]:
    """
    Parse a D&D Beyond type line into (item_type, subtype, rarity, requires_attunement).

    Examples:
        "Weapon (martial, melee)"                         -> weapon, "martial melee", "", False
        "Weapon (any sword), Rare, Requires Attunement"   -> weapon, "any sword", "rare", True
        "Armor (heavy)"                                   -> armor, "heavy", "", False
        "Wondrous Item, Uncommon, Requires Attunement"    -> wondrous_item, "", "uncommon", True
        "Ring, Rare, Requires Attunement by a Spellcaster" -> ring, "", "rare", "by a spellcaster"
        "Scroll of 1st-Level Spells, Common"              -> scroll, "", "common", False
        "Ammunition (+1), Uncommon"                       -> ammunition, "+1", "uncommon", False
    """
    item_type = "other"
    subtype = ""
    rarity = ""
    requires_attunement: bool | str = False

    # Split on top-level commas (respecting parentheses)
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in line:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current).strip())

    if not parts:
        return item_type, subtype, rarity, requires_attunement

    # First part: type name (and optional subtype in parens)
    first = parts[0].strip()

    # Extract subtype in parentheses
    paren_m = re.search(r'\(([^)]+)\)', first)
    if paren_m:
        raw_sub = paren_m.group(1).strip()
        # Normalize: "martial, melee" -> "martial melee"
        subtype = re.sub(r'\s*,\s*', ' ', raw_sub)
        first = first[:paren_m.start()].strip()

    # Normalize type
    # Handle "Scroll of ..." -> scroll
    scroll_m = re.match(r'^scroll\b', first, re.IGNORECASE)
    if scroll_m:
        item_type = "scroll"
    else:
        first_low = first.strip().lower()
        # Handle compound weapon types: "Martial Ranged Weapon", "Firearms Ranged Weapon", etc.
        compound_weapon_m = re.match(
            r'^(simple|martial|firearms?|exotic)\s*(melee|ranged)?\s*weapon',
            first_low
        )
        compound_armor_m = re.match(r'^(light|medium|heavy)\s+armor', first_low)
        if compound_weapon_m:
            item_type = "weapon"
            g1 = compound_weapon_m.group(1).rstrip("s")  # "firearms" → "firearm"
            g2 = compound_weapon_m.group(2)
            if g2:
                subtype = f"{g1} {g2}"
            else:
                subtype = g1
        elif compound_armor_m:
            item_type = "armor"
            subtype = compound_armor_m.group(1)
        else:
            item_type = _TYPE_MAP.get(first_low, "other")

    # Remaining parts: rarity and attunement
    for part in parts[1:]:
        part_low = part.strip().lower()
        # Attunement
        if re.match(r'^requires?\s+attunement', part_low):
            rest = re.sub(r'^requires?\s+attunement\s*', '', part.strip(), flags=re.IGNORECASE).strip()
            if rest:
                requires_attunement = _parse_attunement(rest)
            else:
                requires_attunement = True
            continue
        # Rarity
        rarity_val = _rarity_map_lookup(part_low)
        if rarity_val:
            rarity = rarity_val

    return item_type, subtype, rarity, requires_attunement


def _rarity_map_lookup(s: str) -> str:
    s = s.strip().lower()
    return _RARITY_MAP.get(s, "")


def _build_tags(item_type: str, rarity: str, subtype: str) -> list[str]:
    tags: list[str] = [item_type]

    if rarity:
        tags.append(rarity)

    if item_type == "weapon":
        sub_low = subtype.lower()
        if "ranged" in sub_low:
            tags.append("ranged")
        else:
            tags.append("melee")
        if "simple" in sub_low:
            tags.append("simple")
        elif "martial" in sub_low:
            tags.append("martial")

    if item_type in ("potion", "scroll"):
        tags.append("consumable")

    if item_type in ("ring", "rod", "staff", "wand", "wondrous_item"):
        tags.append("magic_item")

    if rarity in ("uncommon", "rare", "very_rare", "legendary", "artifact"):
        if "magic_item" not in tags:
            tags.append("magic_item")

    return tags


def _is_card_format(lines: list[str]) -> bool:
    for line in lines[1:8]:
        if line.strip().lower() in _CARD_KNOWN_LABELS:
            return True
    return False


# ── Card-format parser ────────────────────────────────────────────────────────

def _parse_card_format(lines: list[str]) -> dict:
    result = _empty_result()
    result["name"] = lines[0].strip()

    idx = 1

    # The type line is typically line 2 (index 1)
    if idx < len(lines):
        type_line = lines[idx].strip()
        # Heuristic: if the line contains known item type words, treat it as the type line
        if re.match(
            r'^(weapon|armor|potion|scroll|wondrous item|ring|rod|staff|wand|tool|'
            r'ammunition|adventuring gear|trade good|vehicle|mount|pack|equipment pack|'
            r'tack|druidic focus|musical instrument|gaming set|artisan)',
            type_line, re.IGNORECASE
        ):
            item_type, subtype, rarity, attunement = _parse_type_line(type_line)
            result["item_type"] = item_type
            result["subtype"] = subtype
            result["rarity"] = rarity
            result["requires_attunement"] = attunement
            idx += 1

    # Parse label/value pairs
    while idx < len(lines) - 1:
        label = lines[idx].strip().lower()
        if label in _CARD_LABEL_MAP:
            field = _CARD_LABEL_MAP[label]
            value = lines[idx + 1].strip()
            _apply_field(result, field, value)
            idx += 2
        else:
            break

    # Remaining lines: description
    desc_lines = [l for l in lines[idx:]]
    result["description"] = "\n\n".join(
        para.strip()
        for para in "\n".join(desc_lines).split("\n\n")
        if para.strip()
    )

    result["tags"] = _build_tags(result["item_type"], result["rarity"], result["subtype"])
    return result


# ── Inline-format parser ──────────────────────────────────────────────────────

def _parse_inline_format(lines: list[str]) -> dict:
    result = _empty_result()
    result["name"] = lines[0].strip()

    idx = 1

    # Type line
    if idx < len(lines):
        type_line = lines[idx].strip()
        if re.match(
            r'^(weapon|armor|potion|scroll|wondrous item|ring|rod|staff|wand|tool|'
            r'ammunition|adventuring gear|trade good|vehicle|mount|pack|equipment pack|'
            r'tack|druidic focus|musical instrument|gaming set|artisan)',
            type_line, re.IGNORECASE
        ):
            item_type, subtype, rarity, attunement = _parse_type_line(type_line)
            result["item_type"] = item_type
            result["subtype"] = subtype
            result["rarity"] = rarity
            result["requires_attunement"] = attunement
            idx += 1

    # Inline label lines, then description
    desc_lines: list[str] = []
    in_description = False

    while idx < len(lines):
        line = lines[idx]
        if not in_description:
            matched = False
            for pattern, field in _INLINE_LABEL_PATTERNS:
                m = pattern.match(line)
                if m:
                    _apply_field(result, field, m.group(1).strip())
                    matched = True
                    break
            if not matched:
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

    result["tags"] = _build_tags(result["item_type"], result["rarity"], result["subtype"])
    return result


def _apply_field(result: dict, field: str, value: str) -> None:
    if field == "cost":
        result["cost"] = value
        result["cost_gp"] = _parse_cost_gp(value)
    elif field == "weight":
        result["weight"] = _parse_weight(value)
    elif field == "properties":
        result["properties"] = [p.strip().lower() for p in re.split(r'[,;]', value) if p.strip()]
    elif field == "damage":
        result["damage"] = value
    elif field == "ac":
        result["ac"] = value
    elif field == "source":
        result["source"] = value
    elif field == "requires_attunement":
        result["requires_attunement"] = _parse_attunement(value)


# ── Public entry point ────────────────────────────────────────────────────────

def parse_item(text: str) -> dict:
    text = _normalize(text)
    lines = [l.strip() for l in text.strip().splitlines()]
    lines = [l for l in lines if l]

    if not lines:
        raise ValueError("Empty text — nothing to parse.")

    if _is_card_format(lines):
        return _parse_card_format(lines)
    return _parse_inline_format(lines)


# ── Validator ─────────────────────────────────────────────────────────────────

def validate_item(data: dict) -> list[str]:
    warnings: list[str] = []
    if not data.get("name"):
        warnings.append("Missing item name")
    if not data.get("item_type") or data.get("item_type") == "other":
        warnings.append("Item type not recognized")
    if not data.get("description"):
        warnings.append("Missing description")
    return warnings
