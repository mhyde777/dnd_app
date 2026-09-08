# app/text_blocks.py
"""Line bookkeeping shared by the D&D Beyond parsers.

Every parser in this package finds structure positionally — "the type line is
the line after the name", "the value is the line after its label" — which only
works on a list with the blank lines taken out. Paragraph breaks live in
exactly those blank lines, though, so dropping them outright flattened every
description into one run-on block, and a table inside one became
indistinguishable from the prose above it.

`SourceLine` keeps both halves: the compacted list the structural passes need,
where each line also remembers where it sat in the original paste, so a
description can be cut back out of the raw text with its blank lines intact.
"""
from __future__ import annotations

from typing import Optional, Sequence


class SourceLine(str):
    """A stripped line that remembers its index in the original paste."""

    __slots__ = ("index",)

    def __new__(cls, value: str, index: int) -> "SourceLine":
        line = super().__new__(cls, value)
        line.index = index
        return line


def split_lines(text: str) -> tuple[list[SourceLine], list[str]]:
    """Return (non-blank lines carrying their origin, the raw lines behind them).

    The compacted lines are fully stripped, which is what every structural pass
    already assumed. The raw lines keep their leading tabs, because a table row
    can open with empty cells — a statblock's ability table is written
    "\\t\\tMod\\tSave" over "STR\\t16\\t+3\\t+3", and stripping those two cells away
    slides the header left and puts "Mod" over the ability names.
    """
    raw = [line.rstrip().lstrip(" ") for line in text.splitlines()]
    lines = [
        SourceLine(line.strip(), i)
        for i, line in enumerate(raw)
        if line.strip()
    ]
    return lines, raw


def raw_slice(
    raw: Sequence[str],
    lines: Sequence[SourceLine],
    start: int,
    stop: Optional[int] = None,
) -> list[str]:
    """The original lines — blanks included — behind ``lines[start:stop]``.

    ``start`` and ``stop`` index the compacted list; ``stop`` is exclusive and
    defaults to the end of the paste.
    """
    if start >= len(lines):
        return []
    begin = lines[start].index
    if stop is None or stop >= len(lines):
        end = len(raw)
    else:
        end = lines[stop].index
    return list(raw[begin:end])


def join_paragraphs(lines: Sequence[str]) -> str:
    """Join raw lines into text whose paragraph breaks are single blank lines.

    Runs of blank lines collapse to one, and leading and trailing blanks go, so
    a description's paragraph structure survives without carrying the paste's
    incidental spacing with it.
    """
    out: list[str] = []
    pending_break = False
    for line in lines:
        if line.strip():
            if pending_break and out:
                out.append("")
            pending_break = False
            out.append(line.rstrip())
        else:
            pending_break = True
    return "\n".join(out)
