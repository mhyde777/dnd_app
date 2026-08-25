# app/bulk_item_import.py
"""
Parse a bulk D&D Beyond item list paste into structured item dicts.

Handles the DnD Beyond positional format:
    <Name>
    [Legacy]           (optional)
    <Type>             (may be absent for some items)
    <Cost>             (e.g. "25 GP" or "--")
    <Weight>           (e.g. "1 lb" or "--")
    [Tags line]        (e.g. "Combat, Damage, Utility" — comma separated)
    <Description>      (multi-line prose)
    View Details Page
    Tags:
    <tag1>
    <tag2>
    <Source>

D&D Beyond's *magic items* listing is a second, different shape, and is
detected and parsed separately (see _parse_magic_item_list):
    <Name>
    <Rarity>           ("Uncommon", "Very Rare", "Varies", ...)
    <Type>             ("Wondrous Item", "Weapon", ...)
    [<Subtype>]        ("Glaive", "Shield")
    <Attunement>       ("Required" or an em dash)
    [<Notes line>]     ("Bonus: Magic, Damage: Force")
    <Type line>        ("Weapon (any sword), rare (requires attunement)")
    <Description>      (multi-line prose)
    View Details Page
    [Tags: ...]
    <Source>
It has no cost or weight, and an item you do not own ends at "View Marketplace"
instead, carrying no type line and no description.

Items without "View Details Page" are treated as incomplete (not owned) and skipped.
Legacy items are included when there is no non-legacy counterpart.

Entry points:
    parse_bulk_items(text, *, include_legacy=True)  -> list[ParsedItemBlock]
    dedupe_prefer_non_legacy(items)                 -> list[ParsedItemBlock]
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.item_parser import (
    _RARITY_MAP, _TYPE_MAP,
    item_key, validate_item,
    _parse_type_line, _parse_cost_gp, _parse_weight, _build_tags, _normalize,
)


# ── Constants ─────────────────────────────────────────────────────────────────

_SKIP_LOWER = frozenset({
    "view details page",
    "tags:",
    "partnered content",
})

_LEGACY_LOWER = "legacy"

# Known DnD Beyond item type strings — these should never be treated as names.
# Omit strings that can also be item names ("Arcane Focus", "Holy Symbol", etc.)
_KNOWN_TYPE_LOWER = frozenset({
    "adventuring gear", "trade good", "food and drink",
    # compound weapon types (always type lines, never item names)
    "simple weapon", "simple melee weapon", "simple ranged weapon",
    "martial weapon", "martial melee weapon", "martial ranged weapon",
    "firearm ranged weapon", "firearms ranged weapon", "exotic weapon",
    # compound armor types
    "light armor", "medium armor", "heavy armor",
})

_COMPOUND_WEAPON_RE = re.compile(
    r"^(simple|martial|firearms?|exotic)\s*(melee|ranged)?\s*weapon$",
    re.IGNORECASE,
)
_COMPOUND_ARMOR_RE = re.compile(
    r"^(light|medium|heavy)\s+armor$",
    re.IGNORECASE,
)


# ── Line-type helpers ─────────────────────────────────────────────────────────

def _looks_like_cost(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r'^([\d,.]+ ?(gp|sp|cp)|--|—)$', s, re.IGNORECASE))


def _looks_like_weight(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r'^([\d.]+ ?lbs?\.?|--|—)$', s, re.IGNORECASE))


def _looks_like_name(line: str) -> bool:
    low = line.strip().lower()
    if not low:
        return False
    if low in _SKIP_LOWER or low == _LEGACY_LOWER:
        return False
    if low in _KNOWN_TYPE_LOWER:
        return False
    if _COMPOUND_WEAPON_RE.match(low) or _COMPOUND_ARMOR_RE.match(low):
        return False
    if _looks_like_cost(line) or _looks_like_weight(line):
        return False
    return True


def _is_source_line(line: str) -> bool:
    """True if the line looks like a source book title rather than a single tag."""
    return bool(re.search(r"[\s'\(\)\:\&0-9]", line.strip()))


def _normalize_lines(text: str) -> list[str]:
    text = _normalize(text)
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]


# ── Block boundary detection ──────────────────────────────────────────────────

def _find_source_indices(lines: list[str]) -> set[int]:
    """
    Return the set of line indices that are source-book titles.
    Source lines appear immediately after a 'View Details Page' / Tags section.
    """
    source_indices: set[int] = set()
    n = len(lines)
    for i, line in enumerate(lines):
        if line.strip().lower() != "view details page":
            continue
        j = i + 1
        in_tags = False
        while j < min(n, i + 12):
            low = lines[j].strip().lower()
            if low == "tags:":
                in_tags = True
            elif in_tags:
                if _is_source_line(lines[j]) and lines[j].strip():
                    source_indices.add(j)
                    break
                # continue scanning single-word tags
            else:
                # No tags section — first non-empty line after VDP is source
                if lines[j].strip():
                    source_indices.add(j)
                    break
            j += 1
    return source_indices


def _find_item_starts(lines: list[str]) -> list[int]:
    """
    Return indices of lines that start an item block.

    Three structural patterns (after optional 'Legacy' line):
        A) name → type → cost → weight
        B) name → Legacy → type → cost → weight
        C) name → cost → weight   (type absent; rarer)
    """
    starts: list[int] = []
    added: set[int] = set()
    n = len(lines)
    source_indices = _find_source_indices(lines)

    for i in range(n):
        if i in added or i in source_indices:
            continue
        if not _looks_like_name(lines[i]):
            continue

        # Pattern B: name → Legacy → type → cost → weight
        if (i + 4 < n
                and lines[i + 1].strip().lower() == _LEGACY_LOWER
                and not _looks_like_cost(lines[i + 2])
                and _looks_like_cost(lines[i + 3])
                and _looks_like_weight(lines[i + 4])):
            starts.append(i)
            added.update({i, i + 1, i + 2})  # consume name, Legacy, type line
            continue

        # Pattern A: name → type → cost → weight  (type is not Legacy/cost/weight)
        if (i + 3 < n
                and lines[i + 1].strip().lower() != _LEGACY_LOWER
                and not _looks_like_cost(lines[i + 1])
                and not _looks_like_weight(lines[i + 1])
                and _looks_like_cost(lines[i + 2])
                and _looks_like_weight(lines[i + 3])):
            starts.append(i)
            added.update({i, i + 1})  # consume name + type line
            continue

        # Pattern C: name → cost → weight  (no type line)
        if (i + 2 < n
                and _looks_like_cost(lines[i + 1])
                and _looks_like_weight(lines[i + 2])):
            starts.append(i)
            added.add(i)

    return starts


# ── Segment parser ────────────────────────────────────────────────────────────

@dataclass
class ParsedItemBlock:
    name: str
    key: str
    data: dict
    warnings: list[str]
    is_legacy: bool


def _parse_item_segment(segment: list[str]) -> tuple[dict, bool] | None:
    """
    Parse a single item block (lines starting at the name).
    Returns (item_dict, is_legacy) or None if the block is incomplete.
    An incomplete block has no 'View Details Page' line.
    """
    if not segment:
        return None

    idx = 0
    name = segment[idx].strip()
    idx += 1

    # Legacy marker
    is_legacy = False
    if idx < len(segment) and segment[idx].strip().lower() == _LEGACY_LOWER:
        is_legacy = True
        idx += 1

    # Optional type line (absent if next line is a cost)
    item_type_raw = ""
    if (idx < len(segment)
            and not _looks_like_cost(segment[idx])
            and not _looks_like_weight(segment[idx])):
        item_type_raw = segment[idx].strip()
        idx += 1

    # Cost
    cost_raw = ""
    if idx < len(segment) and _looks_like_cost(segment[idx]):
        cost_raw = segment[idx].strip()
        idx += 1

    # Weight
    weight_raw = ""
    if idx < len(segment) and _looks_like_weight(segment[idx]):
        weight_raw = segment[idx].strip()
        idx += 1

    remaining = segment[idx:]
    lower_remaining = [line.strip().lower() for line in remaining]

    # Require "View Details Page" — items without it are not owned / incomplete
    if "view details page" not in lower_remaining:
        return None

    vdp_idx = lower_remaining.index("view details page")

    # Strip a comma-separated tags hint from the start of the pre-VDP block
    # (e.g., "Combat, Damage, Utility") — single-word lines stay in description
    dnd_tags: list[str] = []
    desc_start = 0
    if vdp_idx > 0:
        first_line = remaining[0].strip()
        if "," in first_line and re.match(r"^[A-Za-z][A-Za-z ,]+$", first_line):
            parts = [p.strip() for p in first_line.split(",")]
            if all(re.match(r"^[A-Za-z][A-Za-z ]*$", p) for p in parts if p):
                dnd_tags = [p.lower() for p in parts if p]
                desc_start = 1

    desc_lines = remaining[desc_start:vdp_idx]
    desc_text = "\n\n".join(
        para.strip()
        for para in "\n".join(desc_lines).split("\n\n")
        if para.strip()
    )

    # Parse source and canonical tags from after "View Details Page"
    after_vdp = remaining[vdp_idx + 1:]
    source = ""
    page_tags: list[str] = []
    in_tags_section = False

    for line in after_vdp:
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if low == "tags:":
            in_tags_section = True
            continue
        if in_tags_section:
            if _is_source_line(stripped):
                source = stripped
            else:
                page_tags.append(stripped.lower())
        else:
            if not source:
                source = stripped

    # Build structured item dict
    item_type, subtype, rarity, attunement = _parse_type_line(item_type_raw)
    auto_tags = _build_tags(item_type, rarity, subtype)

    seen: dict[str, None] = {}
    for t in auto_tags + dnd_tags + page_tags:
        seen[t] = None
    tags = list(seen.keys())

    cost_str = "" if cost_raw in ("--", "—", "") else cost_raw
    weight_val = _parse_weight(weight_raw) if weight_raw not in ("--", "—", "") else 0.0

    data: dict = {
        "name": name,
        "item_type": item_type,
        "subtype": subtype,
        "rarity": rarity,
        "requires_attunement": attunement,
        "cost": cost_str,
        "cost_gp": _parse_cost_gp(cost_raw),
        "weight": weight_val,
        "properties": [],
        "damage": "",
        "ac": "",
        "description": desc_text,
        "tags": tags,
        "source": source,
    }

    return data, is_legacy


# ── Magic-item listing format ─────────────────────────────────────────────────
#
# A different D&D Beyond view with a different shape: rarity and type as
# separate header lines, no cost or weight, and the canonical type line further
# down. An item you do not own carries none of that -- it ends at "View
# Marketplace" with a "purchase the book" blurb where the description belongs --
# so ownership is what decides whether a block is importable.

_RARITY_WORDS = frozenset(_RARITY_MAP)

# The types this listing uses. A subset of _TYPE_MAP: mundane gear never
# appears here, and admitting it would let a description line masquerade as a
# header.
_MAGIC_TYPE_WORDS = frozenset({
    "weapon", "armor", "potion", "scroll", "wondrous item",
    "ring", "rod", "staff", "wand", "ammunition",
})

_MARKETPLACE_LOWER = "view marketplace"
_DETAILS_LOWER = "view details page"

# "Weapon (any sword), rare (requires attunement)" -- the line _parse_type_line
# already understands, and the one an unowned item never has.
_CANONICAL_TYPE_RE = re.compile(
    r"^(?:{types})\b[^,]*,\s*(?:{rarities})\b".format(
        types="|".join(sorted(_MAGIC_TYPE_WORDS, key=len, reverse=True)),
        rarities="|".join(sorted(_RARITY_WORDS, key=len, reverse=True)),
    ),
    re.IGNORECASE,
)

_NOTES_PREFIX_RE = re.compile(r"^notes\s*:\s*(.+)$", re.IGNORECASE)


def _find_magic_item_starts(lines: list[str]) -> list[int]:
    """Indices where a magic-item block begins: name → [Legacy] → rarity → type."""
    starts: list[int] = []
    n = len(lines)
    for i in range(n):
        if not _looks_like_name(lines[i]):
            continue
        j = i + 1
        if j < n and lines[j].strip().lower() == _LEGACY_LOWER:
            j += 1
        if j + 1 >= n:
            continue
        if lines[j].strip().lower() not in _RARITY_WORDS:
            continue
        if lines[j + 1].strip().lower() not in _MAGIC_TYPE_WORDS:
            continue
        starts.append(i)
    return starts


def is_magic_item_listing(lines: list[str]) -> bool:
    """True when this paste is the magic-item listing rather than the equipment one.

    The equipment listing puts the type on the line after the name, never a
    rarity, so one match is enough to tell them apart.
    """
    return bool(_find_magic_item_starts(lines))


def _split_notes(value: str) -> list[str]:
    """Turn a "Bonus: Magic, Damage: Force" line into individual tags."""
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def _parse_magic_item_segment(segment: list[str]) -> tuple[dict, bool] | None:
    """Parse one magic-item block. None when the item is not owned."""
    if not segment:
        return None

    lower = [line.strip().lower() for line in segment]
    if _DETAILS_LOWER not in lower:
        return None  # unowned: ends at "View Marketplace", nothing to import

    idx = 0
    name = segment[idx].strip()
    idx += 1

    is_legacy = False
    if idx < len(segment) and lower[idx] == _LEGACY_LOWER:
        is_legacy = True
        idx += 1

    header_rarity = segment[idx].strip() if idx < len(segment) else ""
    idx += 1
    header_type = segment[idx].strip() if idx < len(segment) else ""
    idx += 1

    vdp_idx = lower.index(_DETAILS_LOWER)

    # The canonical type line carries the subtype and the attunement clause,
    # so prefer it and fall back to the two header lines only if it is absent.
    type_line = ""
    body_start = idx
    for i in range(idx, vdp_idx):
        if _CANONICAL_TYPE_RE.match(segment[i].strip()):
            type_line = segment[i].strip()
            body_start = i + 1
            break
    else:
        # No canonical line: reconstruct from the header, and take attunement
        # from the "Required" line the header carries instead.
        type_line = f"{header_type}, {header_rarity}"
        if any(l == "required" for l in lower[idx:vdp_idx]):
            type_line += ", Requires Attunement"

    item_type, subtype, rarity, attunement = _parse_type_line(type_line)

    # "Notes: Bonus: Magic, Damage: Force" repeats the header's notes line and
    # is not part of the prose.
    note_tags: list[str] = []
    body: list[str] = []
    for line in segment[body_start:vdp_idx]:
        m = _NOTES_PREFIX_RE.match(line.strip())
        if m:
            note_tags.extend(_split_notes(m.group(1)))
        else:
            body.append(line)

    description = "\n\n".join(
        para.strip()
        for para in "\n".join(body).split("\n\n")
        if para.strip()
    )

    # After the details link: an optional "Tags:" list, then the source book.
    # "Partnered Content" is a marketplace badge, not part of either.
    after = [
        line.strip() for line in segment[vdp_idx + 1:]
        if line.strip() and line.strip().lower() != "partnered content"
    ]
    source = after[-1] if after else ""
    page_tags: list[str] = []
    if after and after[0].lower() == "tags:":
        page_tags = [line.lower() for line in after[1:-1]]

    # Everything in this listing is a magic item by definition, including the
    # common and "varies" ones that _build_tags would not tag on rarity alone.
    tags = _build_tags(item_type, rarity, subtype)
    for tag in ["magic_item"] + note_tags + page_tags:
        if tag not in tags:
            tags.append(tag)

    data: dict = {
        "name": name,
        "item_type": item_type,
        "subtype": subtype,
        "rarity": rarity,
        "requires_attunement": attunement,
        "cost": "",
        "cost_gp": 0.0,
        "weight": 0.0,
        "properties": [],
        "damage": "",
        "ac": "",
        "description": description,
        "tags": tags,
        "source": source,
    }
    return data, is_legacy


def _parse_magic_item_listing(
    lines: list[str],
) -> tuple[list[ParsedItemBlock], list[str]]:
    starts = _find_magic_item_starts(lines)
    if not starts:
        return [], []

    parsed: list[ParsedItemBlock] = []
    unowned: list[str] = []
    boundaries = starts + [len(lines)]
    for start, end in zip(boundaries, boundaries[1:]):
        segment = lines[start:end]
        result = _parse_magic_item_segment(segment)
        if result is None:
            unowned.append(segment[0].strip())
            continue
        data, is_legacy = result
        if not data.get("name", "").strip():
            continue
        parsed.append(ParsedItemBlock(
            name=data["name"],
            key=item_key(data["name"]),
            data=data,
            warnings=validate_item(data),
            is_legacy=is_legacy,
        ))
    return parsed, unowned


# ── Public API ────────────────────────────────────────────────────────────────

def parse_bulk_items(
    text: str,
    *,
    include_legacy: bool = True,
) -> list[ParsedItemBlock]:
    """
    Parse a raw D&D Beyond item list paste.

    By default include_legacy=True so that legacy-only items are kept.
    Call dedupe_prefer_non_legacy() afterwards to drop legacy entries that
    have a non-legacy counterpart in the same paste.
    """
    return parse_bulk_items_report(text, include_legacy=include_legacy)[0]


def parse_bulk_items_report(
    text: str,
    *,
    include_legacy: bool = True,
) -> tuple[list[ParsedItemBlock], list[str]]:
    """As parse_bulk_items, plus the names of blocks skipped as not owned.

    A block you do not own carries a "purchase the book" blurb where its
    description should be, so there is nothing to import -- but silently
    dropping a third of a paste is alarming, so the caller gets to say so.
    """
    lines = _normalize_lines(text)
    if not lines:
        return [], []

    if is_magic_item_listing(lines):
        parsed, unowned = _parse_magic_item_listing(lines)
        if not include_legacy:
            parsed = [item for item in parsed if not item.is_legacy]
        return parsed, unowned

    starts = _find_item_starts(lines)
    if not starts:
        return [], []

    parsed: list[ParsedItemBlock] = []
    unowned: list[str] = []
    boundaries = starts + [len(lines)]

    for start, end in zip(boundaries, boundaries[1:]):
        segment = lines[start:end]
        result = _parse_item_segment(segment)
        if result is None:
            unowned.append(segment[0].strip())
            continue

        data, is_legacy = result
        if is_legacy and not include_legacy:
            continue

        name = data.get("name", "").strip()
        if not name:
            continue

        parsed.append(ParsedItemBlock(
            name=name,
            key=item_key(name),
            data=data,
            warnings=validate_item(data),
            is_legacy=is_legacy,
        ))

    return parsed, unowned


def dedupe_prefer_non_legacy(
    items: Iterable[ParsedItemBlock],
) -> list[ParsedItemBlock]:
    """
    Return one entry per key, preferring the non-legacy version when both exist.
    """
    by_key: dict[str, ParsedItemBlock] = {}
    for item in items:
        existing = by_key.get(item.key)
        if existing is None:
            by_key[item.key] = item
        elif existing.is_legacy and not item.is_legacy:
            by_key[item.key] = item
    return list(by_key.values())
