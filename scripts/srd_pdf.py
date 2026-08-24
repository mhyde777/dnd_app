"""
Structural reader for the SRD 5.2.1 PDF.

`pdftotext -layout` is not usable here. The SRD is two-column, so plain
extraction interleaves the columns, and it throws away the one signal that
makes stat blocks unambiguous: run-in entry names are bold-italic. Without it
a wrapped line like

    Light Crossbow. Ranged Attack Roll: +7, range
    80/320 ft. Hit: 8 (1d8 + 4) Piercing damage

parses as two entries, the second named "80/320 ft" -- exactly the sort of
plausible-looking wrong answer that survives review.

So we read `pdftohtml -xml` instead, which preserves per-run font, size,
colour and <b>/<i> markup, and rebuild the page from that. Roles are decided
by typography, not by guessing:

    title           GillSans-SemiBold, >= 20pt      creature or spell name
    section         GillSans, ~18pt, dark red       "Traits", "Actions"
    entry start     run begins <i><b>Name.</b></i>  a named trait/action
    attribute       run begins <b>Label</b>         "AC", "HP", "Skills", "CR"
    body            anything else                   continuation text

Font *ids* are per-page in pdftohtml's output, so everything resolves through
that page's <fontspec> table rather than by id.

Output is a list of Block objects, each a heading plus already-unwrapped
lines, ready to be rendered into the plain-text shape the app's existing
`parse_statblock()` / `parse_spell()` expect.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator, Optional

# Page is 891 units wide in pdftohtml's coordinate space; the left column sits
# at x=95 and the right at x=470, so anything past this belongs to column two.
COLUMN_SPLIT = 450
# Running feet ("260  System Reference Document 5.2.1") live below this.
FOOTER_Y = 1080

# Monster names are set at 23pt and spell names at 18pt, both GillSans-SemiBold.
# 18pt is also the size of monster section headers ("Traits", "Actions"), but
# those are plain GillSans -- the weight is the only thing separating them, so
# the family test below has to be exact. SC700 is the small-caps variant used
# for sub-headings and is never a title.
_TITLE_MIN_SIZE = 18
_SECTION_SIZE_RANGE = (17, 19)
_SECTION_COLOR = "#88191f"

# U+2212 MINUS SIGN is what InDesign emits for negative modifiers; every
# downstream regex expects ASCII.
_CHAR_FIXES = {
    "−": "-",
    "–": "-",
    "—": "--",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "\xa0": " ",
}


def normalize_chars(text: str) -> str:
    for bad, good in _CHAR_FIXES.items():
        text = text.replace(bad, good)
    return text


@dataclass
class Run:
    """One <text> element: a single typographic run on the page."""

    page: int
    y: int
    x: int
    size: float
    width: int
    family: str
    color: str
    text: str
    lead_style: str      # "bi", "b", "i" or "" -- style of the first inked part
    lead_text: str       # text of that first part

    @property
    def column(self) -> int:
        return 1 if self.x >= COLUMN_SPLIT else 0

    @property
    def is_title(self) -> bool:
        return (
            "GillSans-SemiBold" in self.family
            and "SC700" not in self.family
            and self.size >= _TITLE_MIN_SIZE
        )

    @property
    def is_section(self) -> bool:
        lo, hi = _SECTION_SIZE_RANGE
        return (
            lo <= self.size <= hi
            and self.color == _SECTION_COLOR
            and "GillSans" in self.family
            and "SemiBold" not in self.family
        )

    @property
    def is_entry_start(self) -> bool:
        # Bold-italic run-in name, e.g. <i><b>Evasion.</b></i>
        return self.lead_style == "bi" and self.lead_text.strip().endswith(".")

    @property
    def is_attribute(self) -> bool:
        # Bold label with the value alongside: <b>CR</b> 8 (XP 3,900; PB +3)
        return self.lead_style == "b" and not self.lead_text.strip().endswith(".")


@dataclass
class Block:
    """A titled run of content -- one creature, or one spell."""

    title: str
    page: int
    lines: list[str] = field(default_factory=list)
    ability_rows: list[str] = field(default_factory=list)


class _RunReader(HTMLParser):
    """Tolerant reader for pdftohtml's -xml output.

    It is XML in name only. Overlapping style tags appear in the wild:

        <i><b>Fire Breath (Recharge 5-6)</b></i><b>.<i> </b>Dexterity ...

    where <i> opens inside <b> and closes after </b>. ElementTree rejects the
    whole document over it, so styles are tracked with a stack that pops the
    most recent matching tag and shrugs at anything unmatched.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.runs: list[Run] = []
        self._page = 0
        self._fonts: dict[str, tuple[str, float, str]] = {}
        self._attrs: dict[str, str] = {}
        self._parts: list[tuple[str, frozenset]] = []
        self._styles: list[str] = []
        self._in_text = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "page":
            self._page = int(d.get("number", "0"))
            # Font ids are document-global in a multi-page run: pdftohtml
            # declares each font once, on the page where it first appears.
            # Clearing per page leaves every later page with no font data.
        elif tag == "fontspec":
            self._fonts[d.get("id", "")] = (
                d.get("family", ""),
                float(d.get("size", "0") or 0),
                d.get("color", ""),
            )
        elif tag == "text":
            self._in_text = True
            self._attrs = d
            self._parts = []
            self._styles = []
        elif tag in ("b", "i") and self._in_text:
            self._styles.append(tag)

    def handle_endtag(self, tag):
        if tag == "text" and self._in_text:
            self._emit()
            self._in_text = False
        elif tag in ("b", "i") and self._in_text:
            for i in range(len(self._styles) - 1, -1, -1):
                if self._styles[i] == tag:
                    del self._styles[i]
                    break

    def handle_data(self, data):
        if self._in_text and data:
            self._parts.append((data, frozenset(self._styles)))

    def _emit(self) -> None:
        full = "".join(text for text, _ in self._parts)
        if not full.strip():
            return
        y = int(self._attrs.get("top", "0"))
        if y > FOOTER_Y:
            return  # running foot
        lead_style, lead_text = "", ""
        for text, styles in self._parts:
            if text.strip():
                lead_style = "".join(sorted(styles))
                lead_text = text
                break
        family, size, color = self._fonts.get(self._attrs.get("font", ""), ("", 0.0, ""))
        self.runs.append(Run(
            page=self._page,
            y=y,
            x=int(self._attrs.get("left", "0")),
            size=size,
            width=int(self._attrs.get("width", "0")),
            family=family,
            color=color,
            text=normalize_chars(full),
            lead_style=lead_style,
            lead_text=normalize_chars(lead_text),
        ))


def _pdftohtml_xml(pdf: Path, first: int, last: int) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "srd"
        subprocess.run(
            ["pdftohtml", "-xml", "-i", "-hidden",
             "-f", str(first), "-l", str(last), str(pdf), str(stem)],
            check=True, capture_output=True,
        )
        return Path(f"{stem}.xml").read_text(encoding="utf-8", errors="replace")


def read_runs(pdf: Path, first: int, last: int) -> Iterator[Run]:
    """Yield every inked run in reading order: page, then column, then y."""
    reader = _RunReader()
    reader.feed(_pdftohtml_xml(pdf, first, last))
    reader.close()

    by_page: dict[int, list[Run]] = {}
    for run in reader.runs:
        by_page.setdefault(run.page, []).append(run)
    for page in sorted(by_page):
        page_runs = by_page[page]
        page_runs.sort(key=lambda r: (r.column, r.y, r.x))
        yield from page_runs


# Runs on one baseline can differ by a few units -- small-caps renders "Str"
# as "S" at y=218 and "tr" at y=222 -- so lines group by proximity, not
# equality. Real lines are >= 17 apart, so this can't merge two of them.
_BASELINE_TOLERANCE = 8


@dataclass
class Line:
    """Runs sharing a baseline, in left-to-right order."""

    page: int
    y: int
    column: int
    runs: list[Run]

    @property
    def text(self) -> str:
        """Runs joined, restoring spaces the PDF encodes as horizontal gaps.

        A title split across runs -- "Gray" at x=95 w=47, "Ooze" at x=148 --
        has no space character between them, and naive concatenation yields
        "GrayOoze" (and the key grayooze.json). Small-caps fragments like
        "S" + "tr" abut or overlap, so a gap threshold separates the two cases.
        """
        parts: list[str] = []
        prev: Optional[Run] = None
        for run in self.runs:
            if prev is not None:
                gap = run.x - (prev.x + prev.width)
                needs_space = gap > max(2, prev.size * 0.18)
                if needs_space and parts[-1][-1:].strip() and run.text[:1].strip():
                    parts.append(" ")
            parts.append(run.text)
            prev = run
        return "".join(parts)

    @property
    def head(self) -> Run:
        return self.runs[0]

    @property
    def font_key(self) -> tuple[str, int]:
        """Typeface identity, ignoring the subset prefix and colour.

        A change of typeface between lines marks a new logical block. It is
        what separates a spell's "Duration: ..." line (GillSans 14) from the
        description paragraph beneath it (Cambria 15) -- without it the
        description merges into the duration. Monster entries and their
        continuation lines are both Optima 14, so this never splits those.
        """
        head = self.head
        family = head.family.split("+")[-1]
        # Weight and style are not a paragraph break: a wrapped "Components:"
        # value has a plain-weight head while the label above it is SemiBold,
        # and splitting there strands half the value on its own line.
        for suffix in ("-SemiBold-SC700", "-SemiBold", "-BoldItalic", "-Bold",
                       "-Italic", "-Regular", "-SC700"):
            if family.endswith(suffix):
                family = family[: -len(suffix)]
                break
        return family, round(head.size)


def read_lines(pdf: Path, first: int, last: int) -> list[Line]:
    """Group runs into baseline-ordered lines, column by column."""
    lines: list[Line] = []
    current: list[Run] = []

    def flush() -> None:
        if current:
            ordered = sorted(current, key=lambda r: r.x)
            lines.append(Line(
                page=ordered[0].page,
                y=min(r.y for r in ordered),
                column=ordered[0].column,
                runs=ordered,
            ))
            current.clear()

    for run in read_runs(pdf, first, last):
        if current:
            prev = current[-1]
            same_line = (
                run.page == prev.page
                and run.column == prev.column
                and abs(run.y - current[0].y) <= _BASELINE_TOLERANCE
            )
            if not same_line:
                flush()
        current.append(run)
    flush()
    return lines


_ABILITY_ROW = re.compile(
    # No \b before the name: the grid runs concatenate as "...+0Dex 18 +4 +7"
    # and \b never fires between "0" and "D", so only the first of each row
    # would match. Whitespace after the name is optional too -- some pages
    # render the row as "Str4-3 -3Dex15 +2 +2" with nothing between them.
    r"(?<![A-Za-z])(Str|Dex|Con|Int|Wis|Cha)\s*(\d+)\s*([+-]\d+)\s*([+-]\d+)",
    re.IGNORECASE,
)


def _merge_ability_row(runs: list[Run]) -> Optional[str]:
    """Join same-line runs into one string if they form an ability-grid row.

    The grid renders as small-caps fragments ("S" + "tr") plus a values run,
    three abilities across, so a row only makes sense reassembled.
    """
    joined = "".join(r.text for r in sorted(runs, key=lambda r: r.x))
    return joined if _ABILITY_ROW.search(joined) else None


def _unwrap(lines: list[str]) -> list[str]:
    """Join hard-wrapped continuation lines, repairing hyphenation.

    Every line here already began as its own <text> element, so a line that is
    not an entry start, section header or attribute is by construction a
    continuation of the one above it -- no guessing from punctuation.
    """
    out: list[str] = []
    for line in lines:
        if line.startswith("\0"):        # marker: starts a new logical line
            out.append(line[1:])
        elif out:
            prev = out[-1]
            if prev.endswith("-") and not prev.endswith(" -"):
                out[-1] = prev[:-1] + line.lstrip()
            else:
                out[-1] = prev.rstrip() + " " + line.strip()
        else:
            out.append(line)
    return [re.sub(r"\s+", " ", ln).strip() for ln in out if ln.strip()]


def blocks(pdf: Path, first: int, last: int) -> list[Block]:
    """Segment a page range into titled blocks with unwrapped lines."""
    result: list[Block] = []
    current: Optional[Block] = None
    pending: list[str] = []
    prev_font: Optional[tuple[str, int]] = None

    def close() -> None:
        nonlocal current
        if current is not None:
            current.lines = _unwrap(pending)
            result.append(current)
        pending.clear()

    for line in read_lines(pdf, first, last):
        head = line.head
        text = line.text.strip()
        if not text:
            continue

        if head.is_title:
            # Each title is printed twice, a larger display copy above the
            # real one; collapsing consecutive duplicates keeps one block.
            if current is not None and current.title == text and not current.lines:
                continue
            close()
            current = Block(title=text, page=line.page)
            prev_font = None
            continue

        if current is None:
            continue  # front matter before the first title

        if text == "MOD SAVE" or text.count("MOD SAVE") > 1:
            continue
        if _ABILITY_ROW.search(text):
            current.ability_rows.append(text)
            continue

        starts_line = (
            head.is_section
            or head.is_entry_start
            or head.is_attribute
            or (prev_font is not None and line.font_key != prev_font)
        )
        prev_font = line.font_key
        pending.append(("\0" if starts_line else "") + text)

    close()
    return result
