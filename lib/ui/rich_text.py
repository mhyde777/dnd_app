# ui/rich_text.py
"""Render a parsed description into the HTML the reference cards display.

Descriptions arrive from the D&D Beyond parsers as plain text, and three things
in that text carry structure that a naive `text.replace("\\n", "<br>")` throws
away:

  * **Tables** are tab-delimited rows ("1d100\\tEffect"). HTML collapses runs of
    whitespace, so a pasted-through tab renders as a single space and the
    Bag of Beans effect table reads as one run-on sentence per row.
  * **Paragraph breaks** are blank lines. `<br>` per newline renders a table,
    its title and the prose around it as one undifferentiated block.
  * **Statblocks** ride along inside a description — the creature a spell
    summons, the vehicle an item turns into. They have their own shape (a size
    and type line, single-line fields, an ability table, then Traits and
    Actions sections) and read as a wall of prose without it.

Everything is escaped on the way through: descriptions are pasted text, and
three items in the current library already carry a literal "&".

This module is deliberately Qt-free — it builds a string — so the output can be
asserted in tests without a QApplication.
"""
from __future__ import annotations

import html
import re
from typing import Optional

# Matches the D&D trait lead-in — "Fire Resistance. You have resistance to…" —
# that opens most magic-item properties and every statblock trait. Bounded to a
# short, digit-free phrase so an ordinary sentence ("It has 1d10 + 20 fruit.
# The tree vanishes…") cannot match.
_TRAIT_RE = re.compile(r"^([A-Z][A-Za-z'’\-]*(?: [A-Za-z'’\-]+){0,5})\.\s+(?=[A-Z“\"])")

# A lead-in is title-case; an ordinary sentence that happens to be short and
# end in a period is not. "The apparatus floats on water. It can also go
# underwater…" matches the shape above and must not be bolded, so every word
# after the first has to be capitalised or one of the words a title leaves
# lowercase.
_TITLE_LOWER = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on",
    "or", "the", "to", "with", "your",
})


def _is_title_case(phrase: str) -> bool:
    words = phrase.split()
    return all(w[:1].isupper() or w.lower() in _TITLE_LOWER for w in words[1:])


# A statblock's opening line: "Tiny Construct, Neutral", "Medium undead,
# neutral evil". Finding one is what puts the renderer into statblock mode.
_CREATURE_TYPE_RE = re.compile(
    r"^(Tiny|Small|Medium|Large|Huge|Gargantuan)\s+[A-Za-z]+\b", re.IGNORECASE
)

# Statblock field labels. Outside a statblock these are matched only in their
# unambiguous colon form ("Armor Class: 20"); inside one the bare 2024 form
# ("AC 13", "HP 5 + 5 per spell level") is safe too, because the region is
# already known to be a statblock and a sentence there would not open with one.
_STATBLOCK_LABELS = (
    "Armor Class", "Hit Points", "Proficiency Bonus", "Saving Throws",
    "Damage Vulnerabilities", "Damage Resistances", "Damage Immunities",
    "Condition Immunities", "Vulnerabilities", "Resistances", "Immunities",
    "Initiative", "Languages", "Challenge", "Senses", "Skills", "Speed",
    "Gear", "AC", "HP", "CR", "PB",
)
_LABEL_ALT = "|".join(sorted(_STATBLOCK_LABELS, key=len, reverse=True))
_STATBLOCK_COLON_RE = re.compile(rf"^({_LABEL_ALT}):\s*(.+)$")
_STATBLOCK_BARE_RE = re.compile(rf"^({_LABEL_ALT})\s+(\S.*)$")

# A statblock's section rules. Alone on a line, these are headings.
_SECTION_HEADINGS = frozenset({
    "traits", "actions", "bonus actions", "reactions", "legendary actions",
    "lair actions", "regional effects", "villain actions", "spellcasting",
})

_ABILITIES = frozenset({"str", "dex", "con", "int", "wis", "cha"})

# Defaults match the parchment card palette in lookup_dialog.
_ACCENT = "#7A1F1F"
_RULE = "#C9801A"
_HEADER_BG = "#EFE2CC"
_STRIPE = "#F7EDDC"
_PANEL_BG = "#F9F0DC"


class _Style:
    """The colours one render pass draws with."""

    def __init__(self, accent: str, rule: str, header_bg: str) -> None:
        self.accent = accent
        self.rule = rule
        self.header_bg = header_bg
        self.stripe = _STRIPE
        self.panel = _PANEL_BG


# ── Line classification ───────────────────────────────────────────────────────

def _is_table_row(line: str) -> bool:
    return "\t" in line


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.split("\t")]


def _is_section_heading(line: str) -> bool:
    return line.strip().rstrip(":").lower() in _SECTION_HEADINGS


def _is_table_title(line: str) -> bool:
    """A short label line that titles the table under it, rather than a sentence."""
    stripped = line.strip()
    return (
        0 < len(stripped) <= 60
        and not stripped.endswith((".", "!", "?", ",", ";"))
        and not _is_table_row(stripped)
    )


# ── Inline emphasis ───────────────────────────────────────────────────────────

def _label_html(label: str, value: str, style: _Style) -> str:
    return (
        f'<b style="color:{style.accent};">{html.escape(label)}</b> '
        f'{html.escape(value)}'
    )


def _emphasize(text: str, style: _Style, *, in_statblock: bool = False) -> str:
    """Escape a line, bolding a statblock field label or a trait lead-in."""
    m = _STATBLOCK_COLON_RE.match(text)
    if m:
        return _label_html(m.group(1), m.group(2), style)

    # The bare "AC 13" form is only unambiguous inside a statblock; in ordinary
    # prose a sentence can open with any of these words.
    if in_statblock:
        m = _STATBLOCK_BARE_RE.match(text)
        if m:
            return _label_html(m.group(1), m.group(2), style)

    m = _TRAIT_RE.match(text)
    if m and _is_title_case(m.group(1)):
        rest = text[m.end():]
        if rest:
            return (
                f'<b style="color:{style.accent};">{html.escape(m.group(1))}.</b> '
                f'{html.escape(rest)}'
            )
    return html.escape(text)


# ── Tables ────────────────────────────────────────────────────────────────────

def _prepare_rows(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Split a run of tabbed lines into its header and body rows.

    D&D Beyond repeats the header partway through a wide table — an ability
    block is written as two three-row groups, each carrying its own "Mod / Save"
    line — and those repeats are furniture, not data.
    """
    header = list(rows[0])
    body = [row for row in rows[1:] if row != rows[0]]

    # An ability table's first two columns are unlabelled in the paste. Naming
    # the score column is the difference between a header reading "Mod  Save"
    # adrift over six abilities and one that lines up with what is under it.
    if len(header) >= 2 and all(c == "" for c in header[:2]):
        if body and all(row and row[0].lower() in _ABILITIES for row in body):
            header[1] = "Score"

    return header, body


def _render_table(rows: list[list[str]], style: _Style, title: str = "") -> str:
    header, body = _prepare_rows(rows)
    width = max(len(row) for row in rows)

    out: list[str] = []
    if title:
        out.append(
            f'<p style="margin:8px 0 2px 0; font-weight:bold; '
            f'color:{style.accent};">{html.escape(title)}</p>'
        )

    out.append(
        f'<table border="1" cellpadding="4" cellspacing="0" width="100%" '
        f'style="border-color:{style.rule};">'
    )

    out.append(f'<tr bgcolor="{style.header_bg}">')
    for i in range(width):
        cell = header[i] if i < len(header) else ""
        out.append(
            f'<th align="left" valign="top" style="color:{style.accent};">'
            f'{html.escape(cell)}</th>'
        )
    out.append("</tr>")

    for n, row in enumerate(body):
        # Striped, because these run to a hundred rows and halfway down the eye
        # loses which effect belongs to which die range.
        bg = f' bgcolor="{style.stripe}"' if n % 2 else ""
        out.append(f"<tr{bg}>")
        for i in range(width):
            cell = row[i] if i < len(row) else ""
            # The first column is the key — a die range, an ability, a spell
            # level — and stays on one line so a long effect in the column
            # beside it still lines up against the right key.
            nowrap = ' style="white-space:nowrap;"' if i == 0 and width > 1 else ""
            out.append(f'<td valign="top"{nowrap}>{html.escape(cell)}</td>')
        out.append("</tr>")

    out.append("</table>")
    return "".join(out)


# ── Block rendering ───────────────────────────────────────────────────────────

def _render_lines(lines: list[str], style: _Style, *, in_statblock: bool) -> str:
    """Render one blank-line-delimited block, splitting tables out of it."""
    out: list[str] = []
    prose: list[str] = []

    def flush_prose(before_table: bool = False) -> str:
        """Emit the pending prose. Returns a table title claimed from its end."""
        title = ""
        if before_table and prose and _is_table_title(prose[-1]):
            title = prose.pop().strip()
        if prose:
            out.append(
                '<p style="margin:6px 0; line-height:1.5;">'
                + "<br>".join(
                    _emphasize(line, style, in_statblock=in_statblock)
                    for line in prose
                )
                + "</p>"
            )
            prose.clear()
        return title

    i = 0
    while i < len(lines):
        line = lines[i]

        if _is_table_row(line):
            j = i
            while j < len(lines) and _is_table_row(lines[j]):
                j += 1
            # A header and at least one row. A lone tabbed line is far more
            # likely a stray tab inside a sentence than a one-row table, and
            # boxing it would be worse than spacing it out.
            if j - i >= 2:
                title = flush_prose(before_table=True)
                out.append(
                    _render_table([_cells(l) for l in lines[i:j]], style, title)
                )
            else:
                # An em space, not a plain one: HTML collapses a literal tab to
                # nothing wider than an ordinary word gap.
                prose.append(line.replace("\t", " "))
            i = j
            continue

        if in_statblock and _is_section_heading(line):
            flush_prose()
            out.append(
                f'<p style="margin:10px 0 2px 0; font-weight:bold; '
                f'font-size:15px; color:{style.accent}; '
                f'border-bottom:1px solid {style.rule};">'
                f'{html.escape(line.strip().rstrip(":"))}</p>'
            )
            i += 1
            continue

        prose.append(line)
        i += 1

    flush_prose()
    return "".join(out)


def _to_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip():
            current.append(line.rstrip())
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


# ── Statblocks ────────────────────────────────────────────────────────────────

def _find_statblock(blocks: list[list[str]]) -> Optional[int]:
    """Index of the block that opens an embedded statblock, if there is one.

    The size-and-type line is the marker, and the creature's name is the line
    above it — usually the first line of the same block. The very first line of
    a description is never taken as one: an item whose text opens "Large object
    …" is describing itself, not introducing a creature.
    """
    for n, block in enumerate(blocks):
        for i, line in enumerate(block[:2]):
            if not _CREATURE_TYPE_RE.match(line.strip()):
                continue
            if n == 0 and i == 0:
                continue
            return n
    return None


def _render_statblock(blocks: list[list[str]], style: _Style) -> str:
    """Render the statblock region as its own bordered panel."""
    head = blocks[0]
    name = ""

    if len(head) >= 2 and _CREATURE_TYPE_RE.match(head[1].strip()):
        name, subtitle = head[0].strip(), head[1].strip()
        remainder = head[2:]
    else:
        subtitle = head[0].strip()
        remainder = head[1:]

    out = [
        f'<table width="100%" cellpadding="8" cellspacing="0" border="1" '
        f'style="border-color:{style.rule}; margin:10px 0;">'
        f'<tr><td bgcolor="{style.panel}">'
    ]
    if name:
        out.append(
            f'<p style="margin:0; font-size:17px; font-weight:bold; '
            f'color:{style.accent};">{html.escape(name)}</p>'
        )
    out.append(
        f'<p style="margin:0 0 4px 0; font-style:italic; font-size:11px; '
        f'color:#555;">{html.escape(subtitle)}</p>'
    )
    if remainder:
        out.append(_render_lines(remainder, style, in_statblock=True))
    for block in blocks[1:]:
        out.append(_render_lines(block, style, in_statblock=True))

    out.append("</td></tr></table>")
    return "".join(out)


# ── Public entry point ────────────────────────────────────────────────────────

def render_description(
    text: str,
    *,
    accent: str = _ACCENT,
    rule: str = _RULE,
    header_bg: Optional[str] = None,
) -> str:
    """Render a description's paragraphs, tables and statblocks as HTML."""
    if not text:
        return ""
    style = _Style(accent, rule, header_bg if header_bg is not None else _HEADER_BG)

    blocks = _to_blocks(text)
    start = _find_statblock(blocks)

    prose_blocks = blocks if start is None else blocks[:start]
    out = [_render_lines(b, style, in_statblock=False) for b in prose_blocks]
    if start is not None:
        out.append(_render_statblock(blocks[start:], style))
    return "".join(out)
