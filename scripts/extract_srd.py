#!/usr/bin/env python3
"""
One-time extractor: SRD 5.2.1 PDF -> the app's statblock/spell JSON.

Run this by hand, review `extraction_report.txt`, then commit the JSON. It is
never part of a build, and the PDF is never committed.

    python scripts/extract_srd.py --pdf ~/Downloads/SRD_CC_v5.2.1.pdf \\
        --out srd_content/

The PDF is read structurally (see scripts/srd_pdf.py), then rendered into the
plain-text shape `parse_statblock()` / `parse_spell()` already accept, so the
parsers the app uses for pasted text are the same ones used here -- no second
implementation to keep in sync.

The report is the point of the first run. Assume some entries are wrong and
read it before trusting the output.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from srd_pdf import Block, blocks, normalize_chars  # noqa: E402

from app.item_parser import item_key, parse_item, validate_item  # noqa: E402
from app.spell_parser import parse_spell, spell_key, validate_spell  # noqa: E402
from app.statblock_parser import (  # noqa: E402
    parse_statblock,
    statblock_key,
    validate_statblock,
)

# Printed page ranges, from the table of contents. Printed numbers match PDF
# page numbers in this document (page 1 of the PDF is printed page 1).
# Verified against the document, not just the table of contents: p106 is the
# tail of the casting rules, p176 starts the Rules Glossary, and the Animals
# section runs to the last page of the PDF -- the TOC gives no end page for it,
# and stopping short silently drops the creatures on pp.362-364.
# 175 is the last spell page (Wish); verified that including p176, the start of
# the Rules Glossary, yields the same 338 spells and only sweeps in glossary
# entries the spell filter then has to reject.
SPELL_PAGES = (107, 175)
# One continuous sweep, deliberately: the Monsters A-Z and Animals chapters are
# split at p343/344 mid-creature -- the Zombie's Actions sit on the first page
# of Animals. Extracting the two chapters as separate ranges orphans anything
# that straddles the join.
MONSTER_PAGES = (258, 364)
# Summon spells embed their own stat blocks (Animated Object, Draconic Spirit,
# Otherworldly Steed) in the spells chapter, so it is swept for stat blocks too.
MAGIC_ITEM_PAGES = (209, 253)
SUMMON_PAGES = SPELL_PAGES

_ABILITY = re.compile(
    # No \b before the name: the grid runs concatenate as "...+0Dex 18 +4 +7"
    # and \b never fires between "0" and "D", so only the first of each row
    # would match. Whitespace after the name is optional too -- some pages
    # render the row as "Str4-3 -3Dex15 +2 +2" with nothing between them.
    r"(?<![A-Za-z])(Str|Dex|Con|Int|Wis|Cha)\s*(\d+)\s*([+-]\d+)\s*([+-]\d+)",
    re.IGNORECASE,
)

# A stat block always leads with the size/type/alignment line; anything without
# one is prose that happens to sit under a heading (sidebars, section intros).
_SIZE_TYPE = re.compile(
    r"^(Tiny|Small|Medium|Large|Huge|Gargantuan)\b.*,",
    re.IGNORECASE,
)

# "Level 2 Evocation (Wizard)" / "Evocation Cantrip (Sorcerer, Wizard)"
_SPELL_LEVEL = re.compile(
    r"^(?:Level\s+(?P<lvl>\d+)\s+(?P<school1>\w+)|(?P<school2>\w+)\s+Cantrip)"
    r"\s*(?:\((?P<classes>[^)]*)\))?",
    re.IGNORECASE,
)


def render_statblock(block: Block) -> str:
    """Render a Block as the 2024-format text `parse_statblock()` expects."""
    out: list[str] = [block.title]

    for row in block.ability_rows:
        pass  # emitted below, after the header lines they must follow

    inserted_abilities = False
    for line in block.lines:
        # Ability scores belong immediately after Speed, which is where the
        # PDF puts them and where the parser looks for them.
        if not inserted_abilities and re.match(r"^(Skills|Senses|Languages|CR|Resistances|Immunities|Vulnerabilities|Gear)\b", line):
            out.extend(_render_abilities(block))
            inserted_abilities = True
        out.append(line)

    if not inserted_abilities:
        out.extend(_render_abilities(block))

    return "\n".join(out)


def _render_abilities(block: Block) -> list[str]:
    """Expand the 3-across ability grid into the parser's vertical form.

    The PDF prints `Str 11 +0 +0  Dex 18 +4 +7  Con 14 +2 +2`; the parser wants
    `STR 11 +0` followed by the save on its own line.
    """
    lines: list[str] = []
    for row in block.ability_rows:
        for name, score, mod, save in _ABILITY.findall(row):
            lines.append(f"{name.upper()} {score} {mod}")
            lines.append(save)
    if not lines:
        return lines
    # The "Mod Save" header is one of the signals `_detect_format` uses to
    # pick the 2024 ability parser. Summon stat blocks inside spell
    # descriptions carry no CR or Initiative line, so without it they are read
    # as 2014 format and every score silently comes out as 10.
    return ["Mod Save"] + lines


def render_spell(block: Block) -> tuple[str, dict]:
    """Render a spell Block as text, plus fields the parser can't get itself."""
    extra: dict = {}
    body: list[str] = [block.title]

    for line in block.lines:
        m = _SPELL_LEVEL.match(line)
        if m and "level" not in extra:
            # The SRD combines level, school and class list on one line, which
            # is neither D&D Beyond layout the parser knows.
            extra["level"] = int(m.group("lvl")) if m.group("lvl") else 0
            extra["school"] = (m.group("school1") or m.group("school2") or "").title()
            classes = (m.group("classes") or "").strip()
            if classes:
                extra["classes"] = [c.strip() for c in classes.split(",") if c.strip()]
            continue
        body.append(line)

    return "\n".join(body), extra


# The line under a magic item's name carries its type and rarity:
#   "Wondrous Item, Legendary"
#   "Weapon (any sword), Rare, Requires Attunement"
# item_parser already understands that exact shape, so detection just has to
# recognise a rarity word in the first line or two.
_RARITIES = ("common", "uncommon", "rare", "very rare", "legendary", "artifact", "varies")


def is_magic_item(block: Block) -> bool:
    for line in block.lines[:2]:
        low = line.lower()
        if any(r in low for r in _RARITIES) and len(line) < 160:
            return True
    return False


# The SRD appends attunement to the rarity in parentheses --
#   "Wondrous Item, Rare (Requires Attunement by a Spellcaster)"
# -- while item_parser splits the type line on top-level commas and expects
# attunement as its own part. Left alone, "Rare (Requires Attunement)" matches
# no rarity, so both the rarity and the attunement flag are silently lost.
_ATTUNEMENT_PAREN = re.compile(r"\s*\((Requires Attunement[^)]*)\)", re.IGNORECASE)


def render_item(block: Block) -> str:
    """Render as the "Name / type line / description" text parse_item accepts."""
    lines = list(block.lines)
    if lines:
        lines[0] = _ATTUNEMENT_PAREN.sub(r", \1", lines[0])
    return "\n".join([block.title] + lines)


def extract_magic_items(pdf: Path, first: int, last: int) -> tuple[dict, list[str]]:
    entries, report = {}, []
    for block in blocks(pdf, first, last):
        if not is_magic_item(block):
            if len(block.lines) > 4:
                report.append(f"SKIPPED p{block.page} {block.title!r}: no rarity line")
            continue
        data = parse_item(render_item(block))
        data.setdefault("name", block.title)
        if not data.get("name"):
            data["name"] = block.title
        data["source"] = "SRD 5.2.1"
        key = item_key(data["name"])
        if key in entries:
            report.append(f"DUPLICATE p{block.page} {key}: keeping first")
            continue
        entries[key] = data
        for w in validate_item(data):
            report.append(f"WARN p{block.page} {key}: {w}")
    return entries, report


def is_statblock(block: Block) -> bool:
    return bool(block.ability_rows) and any(
        _SIZE_TYPE.match(line) for line in block.lines[:2]
    )


def is_spell(block: Block) -> bool:
    return any(_SPELL_LEVEL.match(line) for line in block.lines[:2])


def extract_monsters(
    pdf: Path, first: int, last: int, *, quiet_skips: bool = False
) -> tuple[dict, list[str]]:
    entries, report = {}, []
    for block in blocks(pdf, first, last):
        if not is_statblock(block):
            # The spells chapter is swept for the summon stat blocks it embeds,
            # so most of what it yields is spells. Reporting each one as a skip
            # buries the handful of skips that actually want a human look.
            if not quiet_skips and (block.ability_rows or len(block.lines) > 6):
                report.append(f"SKIPPED p{block.page} {block.title!r}: not a stat block")
            continue
        text = render_statblock(block)
        data = parse_statblock(text)
        warnings = validate_statblock(data)
        key = statblock_key(data.get("name") or block.title)
        if key in entries:
            report.append(f"DUPLICATE p{block.page} {key}: keeping first")
            continue
        entries[key] = data
        for w in warnings:
            report.append(f"WARN p{block.page} {key}: {w}")
    return entries, report


def extract_spells(pdf: Path, first: int, last: int) -> tuple[dict, list[str]]:
    entries, report = {}, []
    for block in blocks(pdf, first, last):
        if not is_spell(block):
            if len(block.lines) > 4:
                report.append(f"SKIPPED p{block.page} {block.title!r}: not a spell")
            continue
        text, extra = render_spell(block)
        data = parse_spell(text)
        data.setdefault("name", block.title)
        data.update({k: v for k, v in extra.items() if v not in (None, "", [])})
        warnings = [w for w in validate_spell(data) if "level" not in w.lower()]
        key = spell_key(data.get("name") or block.title)
        if key in entries:
            report.append(f"DUPLICATE p{block.page} {key}: keeping first")
            continue
        entries[key] = data
        for w in warnings:
            report.append(f"WARN p{block.page} {key}: {w}")
    return entries, report


def write_all(out_dir: Path, subdir: str, entries: dict) -> None:
    target = out_dir / subdir
    target.mkdir(parents=True, exist_ok=True)
    for key, data in entries.items():
        (target / key).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", default=Path("srd_content"), type=Path)
    ap.add_argument("--only", choices=("monsters", "spells", "items"),
                    help="limit to one category")
    ap.add_argument("--pages", help="override page range, e.g. 258-262 (for spot checks)")
    ap.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"No such PDF: {args.pdf}", file=sys.stderr)
        return 1

    override = None
    if args.pages:
        lo, _, hi = args.pages.partition("-")
        override = (int(lo), int(hi or lo))

    report: list[str] = []
    counts: Counter = Counter()
    monsters: dict = {}
    spells: dict = {}

    if args.only != "spells":
        ranges = [override] if override else [MONSTER_PAGES, SUMMON_PAGES]
        for lo, hi in ranges:
            found, rep = extract_monsters(
                args.pdf, lo, hi, quiet_skips=(lo, hi) == SUMMON_PAGES and not override
            )
            monsters.update(found)
            report += rep
        counts["statblocks"] = len(monsters)

    if args.only != "monsters":
        lo, hi = override or SPELL_PAGES
        spells, rep = extract_spells(args.pdf, lo, hi)
        report += rep
        counts["spells"] = len(spells)

    items: dict = {}
    if args.only not in ("monsters", "spells"):
        lo, hi = override or MAGIC_ITEM_PAGES
        items, rep = extract_magic_items(args.pdf, lo, hi)
        report += rep
        counts["items"] = len(items)

    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        if monsters:
            write_all(args.out, "statblocks", monsters)
        if spells:
            write_all(args.out, "spells", spells)
        if items:
            write_all(args.out, "items", items)
        manifest = {
            "source": "System Reference Document 5.2.1",
            "license": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/legalcode",
            "attribution": (
                'This work includes material from the System Reference Document 5.2.1 '
                '("SRD 5.2.1") by Wizards of the Coast LLC, available at '
                "https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the "
                "Creative Commons Attribution 4.0 International License."
            ),
            "counts": dict(counts),
            "statblocks": sorted(monsters),
            "spells": sorted(spells),
            "items": sorted(items),
        }
        (args.out / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.out / "extraction_report.txt").write_text(
            "\n".join(report) + "\n", encoding="utf-8"
        )

    for label, n in counts.items():
        print(f"{label}: {n}")
    print(f"warnings: {sum(1 for r in report if r.startswith('WARN'))}")
    print(f"skipped:  {sum(1 for r in report if r.startswith('SKIPPED'))}")
    print(f"dupes:    {sum(1 for r in report if r.startswith('DUPLICATE'))}")
    if args.dry_run:
        for line in report[:40]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
