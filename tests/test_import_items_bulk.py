"""The bulk item importer's decisions about what to write.

The dangerous failure here is a silent overwrite: the same library holds the
bundled SRD items and anything the user has edited by hand, so a re-run of a
paste must not quietly replace them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_items_bulk import gather_inputs, plan_uploads  # noqa: E402


class Block:
    """Stands in for ParsedItemBlock; only .key is consulted."""

    def __init__(self, key):
        self.key = key


def test_directory_contributes_its_text_files_in_order(tmp_path):
    for name in ("page_2.txt", "page_1.txt", "notes.md"):
        (tmp_path / name).write_text("x")

    assert [Path(p).name for p in gather_inputs([str(tmp_path)])] == [
        "page_1.txt", "page_2.txt",
    ]


def test_explicit_files_are_passed_through(tmp_path):
    target = tmp_path / "one.txt"
    target.write_text("x")
    assert gather_inputs([str(target)]) == [str(target)]


def test_existing_entries_are_left_alone_by_default():
    items = [Block("longsword.json"), Block("bag_of_holding.json")]
    upload, skipped = plan_uploads(
        items, ["bag_of_holding.json"], overwrite=False,
    )
    assert [b.key for b in upload] == ["longsword.json"]
    assert [b.key for b in skipped] == ["bag_of_holding.json"]


def test_overwrite_uploads_everything():
    items = [Block("longsword.json"), Block("bag_of_holding.json")]
    upload, skipped = plan_uploads(
        items, ["bag_of_holding.json"], overwrite=True,
    )
    assert len(upload) == 2
    assert skipped == []
