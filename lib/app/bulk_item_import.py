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
    lines = _normalize_lines(text)
    if not lines:
        return []

    starts = _find_item_starts(lines)
    if not starts:
        return []

    parsed: list[ParsedItemBlock] = []
    boundaries = starts + [len(lines)]

    for start, end in zip(boundaries, boundaries[1:]):
        segment = lines[start:end]
        result = _parse_item_segment(segment)
        if result is None:
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

    return parsed


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
