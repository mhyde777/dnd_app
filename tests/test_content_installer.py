import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app import srd_content  # noqa: E402
from app.content_installer import install_srd  # noqa: E402


class FakeStorage:
    """Stands in for any storage provider; they all share this interface."""

    def __init__(self, existing=(), fail_keys=(), raise_on_list=False):
        self.statblocks = {}
        self.spells = {}
        self.items = {}
        self._existing = set(existing)
        self._fail_keys = set(fail_keys)
        self._raise_on_list = raise_on_list

    def list_statblock_keys(self):
        if self._raise_on_list:
            raise RuntimeError("backend unreachable")
        return sorted(self._existing | set(self.statblocks))

    def list_spell_keys(self):
        if self._raise_on_list:
            raise RuntimeError("backend unreachable")
        return sorted(self.spells)

    def list_item_keys(self):
        if self._raise_on_list:
            raise RuntimeError("backend unreachable")
        return sorted(self.items)

    def save_statblock(self, key, data):
        if key in self._fail_keys:
            return False
        self.statblocks[key] = data
        return True

    def save_spell(self, key, data):
        self.spells[key] = data
        return True

    def save_item(self, key, data):
        self.items[key] = data
        return True


@pytest.fixture(autouse=True)
def _fake_payload(monkeypatch):
    """Two entries per category, so counts don't shift with the real content."""
    entries = {
        "statblocks": [("goblin.json", {"name": "Goblin"}),
                       ("orc.json", {"name": "Orc"})],
        "spells": [("fireball.json", {"name": "Fireball"}),
                   ("shield.json", {"name": "Shield"})],
        "items": [("bag_of_holding.json", {"name": "Bag of Holding"}),
                  ("cloak_of_elvenkind.json", {"name": "Cloak of Elvenkind"})],
    }
    monkeypatch.setattr(srd_content, "is_available", lambda: True)
    monkeypatch.setattr(
        srd_content, "counts",
        lambda: {"statblocks": 2, "spells": 2, "items": 2},
    )
    monkeypatch.setattr(srd_content, "iter_entries", lambda c: iter(entries[c]))
    monkeypatch.setattr(srd_content, "version", lambda: "SRD test")


def test_installs_every_entry():
    storage = FakeStorage()
    result = install_srd(storage)
    assert result.installed == 6
    assert result.skipped == 0
    assert result.failed == []
    assert set(storage.statblocks) == {"goblin.json", "orc.json"}
    assert set(storage.spells) == {"fireball.json", "shield.json"}
    assert set(storage.items) == {"bag_of_holding.json", "cloak_of_elvenkind.json"}


def test_skips_entries_already_present():
    # A user edit must survive a re-run rather than being overwritten.
    storage = FakeStorage(existing=["goblin.json"])
    result = install_srd(storage, categories=["statblocks"])
    assert result.installed == 1
    assert result.skipped == 1
    assert "goblin.json" not in storage.statblocks


def test_skip_existing_off_overwrites():
    storage = FakeStorage(existing=["goblin.json"])
    result = install_srd(storage, categories=["statblocks"], skip_existing=False)
    assert result.installed == 2
    assert result.skipped == 0


def test_cancel_stops_promptly_and_leaves_resumable_state():
    storage = FakeStorage()
    cancel = threading.Event()

    def on_progress(category, index, total, key):
        if index == 1:
            cancel.set()  # user hits Cancel on the first entry

    result = install_srd(storage, progress=on_progress, cancel=cancel)
    assert result.cancelled is True
    assert result.installed == 0
    assert storage.statblocks == {}

    # Resuming installs what the cancelled run did not.
    again = install_srd(storage)
    assert again.cancelled is False
    assert again.installed == 6


def test_failures_are_recorded_not_raised():
    storage = FakeStorage(fail_keys=["orc.json"])
    result = install_srd(storage, categories=["statblocks"])
    assert result.installed == 1
    assert result.failed == ["statblocks/orc.json"]


def test_unlistable_backend_still_installs():
    # Not being able to enumerate the backend means nothing can be skipped --
    # it is not a reason to refuse the install.
    storage = FakeStorage(raise_on_list=True)
    result = install_srd(storage, categories=["statblocks"])
    assert result.installed == 2


def test_unknown_category_is_ignored():
    storage = FakeStorage()
    result = install_srd(storage, categories=["statblocks", "nonsense"])
    assert result.installed == 2


def test_progress_reports_each_entry():
    storage = FakeStorage()
    seen = []
    install_srd(storage, categories=["spells"],
                progress=lambda c, i, t, k: seen.append((c, i, t, k)))
    assert seen == [
        ("spells", 1, 2, "fireball.json"),
        ("spells", 2, 2, "shield.json"),
    ]
