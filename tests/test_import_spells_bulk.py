from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from import_spells_bulk import _canonical_spell_key, _prepare_api_replacements


class _FakeAPI:
    def __init__(self, keys, spell_data):
        self._keys = keys
        self._spell_data = spell_data

    def list_spell_keys(self):
        return list(self._keys)

    def get_spell(self, key):
        return self._spell_data.get(key)


def _spell(key: str, *, is_legacy: bool):
    return SimpleNamespace(key=key, is_legacy=is_legacy)


def test_canonical_spell_key_normalizes_legacy_suffixes():
    assert _canonical_spell_key("charm_person_legacy.json") == "charm_person.json"
    assert _canonical_spell_key("charm_person(legacy).json") == "charm_person.json"
    assert _canonical_spell_key("charm_person.json") == "charm_person.json"


def test_prepare_api_replacements_skips_legacy_when_nonlegacy_exists():
    api = _FakeAPI(
        keys=["charm_person.json"],
        spell_data={"charm_person.json": {"name": "Charm Person"}},
    )

    delete_keys, skip_upload_keys = _prepare_api_replacements(
        api,
        [_spell("charm_person_legacy.json", is_legacy=True)],
    )

    assert delete_keys == set()
    assert skip_upload_keys == {"charm_person_legacy.json"}


def test_prepare_api_replacements_deletes_legacy_when_nonlegacy_uploaded():
    api = _FakeAPI(
        keys=["charm_person_legacy.json"],
        spell_data={"charm_person_legacy.json": {"name": "Charm Person (Legacy)"}},
    )

    delete_keys, skip_upload_keys = _prepare_api_replacements(
        api,
        [_spell("charm_person.json", is_legacy=False)],
    )

    assert delete_keys == {"charm_person_legacy.json"}
    assert skip_upload_keys == set()
