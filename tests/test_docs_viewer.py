"""
Help → Documentation: locating the shipped docs, and rendering them.

The rendering tests are the point of this file. Qt's own Markdown importer
looks like it would do the job and quietly mangles exactly the things these
docs are made of, so the converter is not an implementation detail that can be
swapped without noticing.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import docs_content

pytest.importorskip("markdown")
from ui.docs_window import render  # noqa: E402


# --------------------------------------------------------------------------
# Locating
# --------------------------------------------------------------------------

def test_every_listed_doc_actually_ships():
    """A contents entry with no file behind it is a dead link in the UI."""
    missing = [
        doc.filename
        for _heading, docs in docs_content.SECTIONS
        for doc in docs
        if docs_content.resolve(doc.filename) is None
    ]
    assert missing == []


def test_available_matches_the_full_registry_in_a_source_checkout():
    listed = [d.filename for _h, docs in docs_content.SECTIONS for d in docs]
    present = [d.filename for _h, docs in docs_content.available() for d in docs]
    assert listed == present


def test_both_link_spellings_resolve_to_one_file():
    """Docs inside docs/ link as `storage.md`; the README links as
    `docs/storage.md`. Both appear, and both must work."""
    assert docs_content.resolve("storage.md") == docs_content.resolve("docs/storage.md")


@pytest.mark.parametrize("attempt", [
    "../README.md",
    "../../../etc/passwd",
    "docs/../../secrets.md",
    "..\\..\\windows.md",
    "/etc/passwd",
])
def test_path_traversal_is_refused(attempt):
    """A doc name arrives from a link inside a Markdown file, so it is input.
    `lstrip("./")` once let "../README.md" through as "README.md" -- it strips
    characters, not a prefix."""
    assert docs_content.resolve(attempt) is None


def test_a_leading_dot_slash_is_still_an_ordinary_link():
    assert docs_content.resolve("./storage.md") == docs_content.resolve("storage.md")


def test_an_unknown_doc_resolves_to_nothing_rather_than_raising():
    assert docs_content.resolve("no_such_doc.md") is None
    assert docs_content.read("no_such_doc.md") is None


def test_the_window_has_something_to_open_on():
    assert docs_content.first_doc() is not None


def test_find_maps_a_link_target_back_to_its_registry_entry():
    assert docs_content.find("storage.md").title == "Where Your Data Lives"
    # Links from the README carry the directory; the entry is the same.
    assert docs_content.find("docs/storage.md").title == "Where Your Data Lives"
    assert docs_content.find("architecture.md").title == "Architecture"
    assert docs_content.find("not-listed.md") is None


# --------------------------------------------------------------------------
# Rendering — the things Qt's setMarkdown() gets wrong
# --------------------------------------------------------------------------

def test_fenced_code_blocks_survive():
    """The reason this app does not use QTextBrowser.setMarkdown(): it turns
    fenced blocks into ordinary paragraphs, and these docs are largely shell
    commands, where losing monospace and indentation loses the meaning."""
    html = render("Text.\n\n```bash\npip install flask\ncd /tmp\n```\n")
    assert "<pre>" in html
    assert "pip install flask" in html


def test_directory_layouts_keep_their_indentation():
    html = render("```\nroot/\n    statblocks/goblin.json\n```\n")
    body = html[html.index("<pre>"):]
    assert "    statblocks/goblin.json" in body


def test_tables_render_with_rules():
    html = render("| A | B |\n|---|---|\n| 1 | 2 |\n")
    assert "<table" in html and "border=" in html
    assert "<th>A</th>" in html.replace(" ", "").replace("\n", "") or "A" in html


def test_headings_get_anchors_so_cross_links_can_land():
    """`architecture.md#storage-providers` is a real link in these docs."""
    html = render("## Storage providers\n\ntext\n")
    assert 'id="storage-providers"' in html


def test_inline_code_is_marked_up():
    assert "<code>" in render("Use `open_storage()` for that.\n")


def test_remote_images_are_dropped_not_shown_broken():
    """Build badges cannot load with no network; a broken-image glyph in a
    help window looks like the app is broken."""
    html = render("![Python](https://img.shields.io/badge/python-3.10-blue)\n")
    assert "img.shields.io" not in html
    assert "<img" not in html


def test_local_images_are_left_alone():
    html = render("![icon](images/d20_icon.png)\n")
    assert "<img" in html and "d20_icon.png" in html


def test_links_are_preserved_for_the_click_handler():
    html = render("See [storage](storage.md#the-providers).\n")
    assert 'href="storage.md#the-providers"' in html


def test_render_produces_a_themed_document():
    html = render("# Title\n")
    assert html.startswith("<html>") and "<style>" in html


def test_every_shipped_doc_renders_without_error():
    """Catches a doc whose Markdown trips the converter — a released build
    with a page that raises on click is worse than one with no viewer."""
    for _heading, docs in docs_content.available():
        for doc in docs:
            text = docs_content.read(doc.filename)
            assert text, doc.filename
            html = render(text)
            assert "<body>" in html, doc.filename


# --------------------------------------------------------------------------
# Cross-links between the real docs
# --------------------------------------------------------------------------

def test_relative_links_between_shipped_docs_all_resolve():
    """A link to another page that the viewer cannot open is a dead end. Only
    checks links to .md files; external URLs are the browser's problem."""
    import re

    link_re = re.compile(r"\]\(([^)]+\.md)(?:#[^)]*)?\)")
    broken = []
    for _heading, docs in docs_content.available():
        for doc in docs:
            text = docs_content.read(doc.filename) or ""
            for target in link_re.findall(text):
                if target.startswith(("http://", "https://")):
                    continue
                if docs_content.resolve(target) is None:
                    broken.append(f"{doc.filename} -> {target}")
    assert broken == []
