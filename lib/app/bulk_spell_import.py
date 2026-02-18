from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.spell_parser import parse_spell, spell_key, validate_spell


_LEVEL_TOKEN_RE = re.compile(r"^(?:cantrip|[1-9](?:st|nd|rd|th))$", re.IGNORECASE)
_BLOCK_BREAK_MARKERS = {"view details page", "tags:", "available for:"}


@dataclass
class ParsedSpellBlock:
    name: str
    key: str
    data: dict
    warnings: list[str]
    is_legacy: bool



def _normalize_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]



def _looks_like_spell_name(line: str) -> bool:
    if not line:
        return False
    lower = line.lower()
    if lower in {
        "level",
        "casting time",
        "range/area",
        "components",
        "duration",
        "school",
        "attack/save",
        "damage/effect",
    }:
        return False
    return not line.endswith(":")



def _find_spell_starts(lines: list[str]) -> list[int]:
    starts: list[int] = []
    for idx in range(len(lines) - 1):
        if _LEVEL_TOKEN_RE.match(lines[idx]) and _looks_like_spell_name(lines[idx + 1]):
            starts.append(idx)
    return starts



def _cut_block_metadata(block_lines: list[str]) -> list[str]:
    for idx, line in enumerate(block_lines):
        if line.strip().lower() in _BLOCK_BREAK_MARKERS:
            return block_lines[:idx]
    return block_lines



def _extract_parseable_spell_text(segment: list[str]) -> tuple[str, bool] | None:
    if len(segment) < 3:
        return None

    name = segment[1].strip()
    is_legacy = any(line.strip().lower() == "legacy" for line in segment[:8])

    level_idx = -1
    for idx, line in enumerate(segment):
        if line.strip().lower() == "level":
            level_idx = idx
            break

    if level_idx < 0:
        return None

    block = _cut_block_metadata(segment[level_idx:])
    parse_text = "\n".join([name] + block)
    return parse_text, is_legacy



def parse_bulk_spells(text: str, *, include_legacy: bool = False) -> list[ParsedSpellBlock]:
    lines = _normalize_lines(text)
    if not lines:
        return []

    starts = _find_spell_starts(lines)
    if not starts:
        return []

    parsed: list[ParsedSpellBlock] = []
    boundaries = starts + [len(lines)]

    for start, end in zip(boundaries, boundaries[1:]):
        segment = lines[start:end]
        built = _extract_parseable_spell_text(segment)
        if built is None:
            continue

        parse_text, is_legacy = built
        if is_legacy and not include_legacy:
            continue

        try:
            data = parse_spell(parse_text)
        except Exception:
            continue

        name = data.get("name", "").strip()
        if not name:
            continue

        parsed.append(
            ParsedSpellBlock(
                name=name,
                key=spell_key(name),
                data=data,
                warnings=validate_spell(data),
                is_legacy=is_legacy,
            )
        )

    return parsed



def dedupe_prefer_non_legacy(spells: Iterable[ParsedSpellBlock]) -> list[ParsedSpellBlock]:
    by_key: dict[str, ParsedSpellBlock] = {}
    for spell in spells:
        existing = by_key.get(spell.key)
        if existing is None:
            by_key[spell.key] = spell
            continue
        if existing.is_legacy and not spell.is_legacy:
            by_key[spell.key] = spell
    return list(by_key.values())
