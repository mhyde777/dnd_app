"""
The documentation that ships with the app.

Help → Documentation reads the same Markdown files that live in `docs/` and
get published on the repository, rather than a second copy written for the
app. One source means they cannot drift, and it means a fix to a doc reaches
users through the ordinary release rather than needing a web page updated.

They are shipped in the bundle (see `pyinstaller.spec`), so the viewer works
offline and describes *the version actually running* -- someone on 0.4.2
reading the docs for 0.6 is worse than no docs at all.

This module is deliberately Qt-free: it locates and reads, and the viewer in
`ui/docs_window.py` decides how to present.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class Doc:
    """One document in the contents list."""

    filename: str      # as it appears in links between docs, e.g. "storage.md"
    title: str         # what the contents list calls it
    blurb: str         # one line, shown as the list item's tooltip


#: Section heading -> the docs under it, in reading order.
#:
#: Curated rather than a directory listing, for two reasons: a filename is not
#: a title ("using-the-tracker.md" is "Running a Combat"), and the order that
#: helps someone learn the app is not alphabetical. A doc added to `docs/` but
#: not named here simply does not appear -- which is the right default for the
#: notes-to-self that accumulate in a docs directory.
SECTIONS: List[tuple] = [
    ("Using the tracker", [
        Doc("README.md", "Overview",
            "What the app is and how to get it running"),
        Doc("using-the-tracker.md", "Running a Combat",
            "Initiative, HP, conditions and turns"),
        Doc("storage.md", "Where Your Data Lives",
            "Storage providers: folders, Dropbox, WebDAV, S3 and more"),
        Doc("importing-content.md", "Importing Content",
            "Bringing in monsters, spells and magic items"),
        Doc("foundry-setup.md", "Connecting to Foundry VTT",
            "Two-way sync with a Foundry game"),
    ]),
    ("Installing and updating", [
        Doc("auto-update.md", "In-App Updating",
            "How the app updates itself, and how to roll back"),
        Doc("updating-windows.md", "Windows",
            "Installing and updating on Windows"),
        Doc("packaging-macos.md", "macOS",
            "The state of macOS packaging"),
    ]),
    ("Under the hood", [
        Doc("architecture.md", "Architecture",
            "How the app is put together, for contributors"),
        Doc("CHANGELOG.md", "Changelog",
            "What changed in each version"),
    ]),
]


def roots() -> List[Path]:
    """Where documentation might live, best candidate first.

    The bundle keeps the same shape as the source tree -- `docs/` beside a
    top-level `README.md` -- so one search order serves both.
    """
    roots: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    # lib/app/docs_content.py -> repo root is three levels up
    roots.append(Path(__file__).resolve().parent.parent.parent)
    roots.append(Path(os.getcwd()))
    return roots


def _clean(filename: str) -> str:
    """A doc name reduced to a safe relative path, or "" if it isn't one.

    The traversal check runs on the *original* text. An earlier version
    stripped first with `lstrip("./")`, which removes leading `.` and `/`
    characters rather than a `./` prefix -- so "../README.md" arrived at the
    check as "README.md" and walked straight out of the docs directory.
    """
    name = filename.strip().replace("\\", "/")
    if not name or ".." in name.split("/"):
        return ""
    while name.startswith("./"):
        name = name[2:]
    name = name.lstrip("/")
    return name


def resolve(filename: str) -> Optional[Path]:
    """The file for a doc name, or None if this build does not ship it.

    `docs/` is searched before the root so that a link written as either
    `storage.md` or `docs/storage.md` -- both spellings appear in the docs,
    depending on whether the linking file is itself in `docs/` -- lands on the
    same file.
    """
    name = _clean(filename)
    if not name:
        return None
    for root in roots():
        for candidate in (root / "docs" / name, root / name):
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
    return None


def read(filename: str) -> Optional[str]:
    """A doc's Markdown, or None when it is missing or unreadable."""
    path = resolve(filename)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def available() -> List[tuple]:
    """SECTIONS filtered to the docs this build actually has.

    A source checkout has all of them; a bundle has whatever the spec shipped.
    Listing a doc that is not there produces a contents entry that errors when
    clicked, so it is filtered here instead.
    """
    out = []
    for heading, docs in SECTIONS:
        present = [doc for doc in docs if resolve(doc.filename) is not None]
        if present:
            out.append((heading, present))
    return out


def first_doc() -> Optional[Doc]:
    """What to open the window on."""
    for _heading, docs in available():
        if docs:
            return docs[0]
    return None


def find(filename: str) -> Optional[Doc]:
    """The registry entry for a filename, if it is one we list."""
    name = _clean(filename)
    if not name:
        return None
    name = name.split("/")[-1]
    for _heading, docs in SECTIONS:
        for doc in docs:
            if doc.filename == name:
                return doc
    return None
