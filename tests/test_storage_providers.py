"""
The storage provider layer: the shared contract, the registry, and each
backend's wire format.

The backends are tested through the *public* interface (`save_spell`,
`list_statblock_keys`, ...) rather than the four primitives, because that is
what the app calls and what a new provider has to get right.
"""
from __future__ import annotations

import json
import os

import pytest

from app.storage import providers
from app.storage.base import StorageBackend
from app.storage.folder import FolderStorage
from app.storage.http import HttpStorage
from app.storage.s3 import S3Storage, _signing_key, canonical_query, canonical_request
from app.storage.webdav import WebDavStorage
from app import settings_sync


# --------------------------------------------------------------------------
# The shared contract
# --------------------------------------------------------------------------

class MemoryStorage(StorageBackend):
    """Minimal provider, to prove the base class supplies the rest."""

    provider_id = "memory"

    def __init__(self):
        self.data = {}

    def _list(self, collection):
        return sorted(self.data.get(collection, {}))

    def _read(self, collection, key):
        return self.data.get(collection, {}).get(key)

    def _write(self, collection, key, data):
        self.data.setdefault(collection, {})[key] = data

    def _delete(self, collection, key):
        self.data.get(collection, {}).pop(key, None)


def test_four_primitives_supply_the_whole_interface():
    store = MemoryStorage()
    store.save_statblock("goblin.json", {"name": "Goblin"})
    store.save_spell("fireball.json", {"level": 3})
    store.save_item("rope.json", {"cost": "1 gp"})
    store.put_json("fight.json", {"round": 2})

    assert store.list_statblock_keys() == ["goblin.json"]
    assert store.get_spell("fireball.json") == {"level": 3}
    assert store.list_item_keys() == ["rope.json"]
    assert store.get_json("fight.json") == {"round": 2}
    assert store.get_statblock("missing.json") is None

    assert store.delete_spell("fireball.json") is True
    assert store.list_spell_keys() == []


def test_synced_settings_blob_is_never_offered_as_an_encounter():
    store = MemoryStorage()
    store.put_json("fight.json", {})
    store.put_json(settings_sync.REMOTE_KEY, {"settings": {}})
    # Every provider inherits this filter, so a new backend cannot forget it.
    assert store.list() == ["fight.json"]


def test_dataclasses_are_encoded_before_reaching_a_provider():
    from app.creature import Monster

    store = MemoryStorage()
    store.put_json("party.json", {"creatures": [Monster(name="Ogre", max_hp=59)]})
    stored = store.data["encounters"]["party.json"]
    # A provider only ever sees plain JSON types.
    assert json.dumps(stored)
    assert stored["creatures"][0]["_name"] == "Ogre"


# --------------------------------------------------------------------------
# FolderStorage
# --------------------------------------------------------------------------

def test_folder_round_trip_and_layout(tmp_path):
    store = FolderStorage(str(tmp_path))
    store.put_json("goblin_caves.json", {"round": 1})
    store.save_statblock("goblin.json", {"name": "Goblin"})
    store.save_spell("shield.json", {"level": 1})
    store.save_item("rope.json", {"cost": "1 gp"})

    # Encounters stay flat at the top; the rest live in named subdirectories.
    assert (tmp_path / "goblin_caves.json").is_file()
    assert (tmp_path / "statblocks" / "goblin.json").is_file()
    assert (tmp_path / "spells" / "shield.json").is_file()
    assert (tmp_path / "items" / "rope.json").is_file()

    assert store.list() == ["goblin_caves.json"]
    assert store.get_statblock("goblin.json") == {"name": "Goblin"}


def test_folder_ignores_non_json_and_hidden_files(tmp_path):
    store = FolderStorage(str(tmp_path))
    (tmp_path / "notes.txt").write_text("not an encounter")
    (tmp_path / ".hidden.json").write_text("{}")
    store.put_json("real.json", {})
    assert store.list() == ["real.json"]


def test_folder_write_is_atomic(tmp_path):
    """A sync client must never see a half-written file."""
    store = FolderStorage(str(tmp_path))
    store.put_json("fight.json", {"round": 1})
    store.put_json("fight.json", {"round": 2})
    assert store.get("fight.json") == {"round": 2}
    # The temp file used for the rename must not be left behind, or it shows
    # up in the encounter list as garbage.
    assert [p.name for p in tmp_path.glob("*.tmp")] == []


def test_folder_treats_corrupt_json_as_absent(tmp_path):
    """A file mid-download from a sync client must not crash the app."""
    store = FolderStorage(str(tmp_path))
    (tmp_path / "half.json").write_text('{"round":')
    assert store.get("half.json") is None


def test_folder_missing_delete_is_not_an_error(tmp_path):
    FolderStorage(str(tmp_path)).delete("never_existed.json")


# --------------------------------------------------------------------------
# HttpStorage — the response shapes people's own servers return
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload,expected", [
    (["a.json", "b.json"], ["a.json", "b.json"]),
    ({"items": ["a.json"]}, ["a.json"]),
    ({"data": ["a.json"]}, ["a.json"]),
    ({"data": {"items": ["a.json"]}}, ["a.json"]),
    ({"keys": ["a.json"]}, ["a.json"]),
    ([{"key": "a.json"}, {"key": "b.json"}], ["a.json", "b.json"]),
    ([{"name": "a.json"}], ["a.json"]),
    ({"results": [{"filename": "a.json"}]}, ["a.json"]),
])
def test_http_accepts_every_documented_list_shape(payload, expected):
    # These tolerances are load-bearing: people have written their own servers
    # against this client and each picked a different shape.
    assert HttpStorage._as_key_list(payload) == expected


def test_http_rejects_a_shape_it_cannot_read():
    assert HttpStorage._as_key_list({"unexpected": 5}) is None


def test_http_unwraps_data_envelopes():
    assert HttpStorage._unwrap({"data": {"name": "Goblin"}}) == {"name": "Goblin"}
    assert HttpStorage._unwrap({"name": "Goblin"}) == {"name": "Goblin"}


def test_http_urls_are_scoped_per_collection():
    store = HttpStorage("http://example.test:8000/")
    assert store._key_url("spells", "fireball.json") == (
        "http://example.test:8000/v1/spells/fireball.json"
    )
    # /v1/items is the equipment collection, never the encounter listing.
    assert store._collection_url("encounters") == "http://example.test:8000/v1/encounters"


def test_http_sends_the_api_key_only_when_there_is_one():
    assert "X-Api-Key" not in HttpStorage("http://x.test").session.headers
    assert HttpStorage("http://x.test", "sekrit").session.headers["X-Api-Key"] == "sekrit"


# --------------------------------------------------------------------------
# WebDAV
# --------------------------------------------------------------------------

_MULTISTATUS = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/dav/alice/DnD%20Tracker/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/alice/DnD%20Tracker/spells/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/alice/DnD%20Tracker/goblin%20caves.json</d:href>
    <d:propstat><d:prop><d:resourcetype/></d:prop></d:propstat>
  </d:response>
</d:multistatus>"""


def test_webdav_listing_skips_collections_and_decodes_names():
    names = WebDavStorage._names_from_multistatus(
        _MULTISTATUS, "/dav/alice/DnD Tracker/"
    )
    # The collection itself and the spells/ subcollection are not encounters.
    assert names == ["goblin caves.json"]


def test_webdav_urls_encode_the_folder_and_key():
    store = WebDavStorage("https://cloud.test/dav/alice", folder="DnD Tracker")
    assert store._dir_url("encounters") == "https://cloud.test/dav/alice/DnD%20Tracker"
    assert store._dir_url("spells") == (
        "https://cloud.test/dav/alice/DnD%20Tracker/spells"
    )
    assert store._key_url("spells", "mage hand.json") == (
        "https://cloud.test/dav/alice/DnD%20Tracker/spells/mage%20hand.json"
    )


# --------------------------------------------------------------------------
# S3 — the hand-rolled SigV4
# --------------------------------------------------------------------------

def test_signing_key_matches_the_published_aws_vector():
    """The one part of SigV4 with an official test vector. If this passes, the
    HMAC chain is right and any failure is in the canonical request."""
    derived = _signing_key(
        "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        "20120215",
        "us-east-1",
        service="iam",
    )
    assert derived.hex() == (
        "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"
    )


def test_canonical_query_uses_percent20_not_plus():
    """urlencode would spell this space `+` and every request would 403,
    because the signature is computed over this exact string."""
    assert canonical_query({"prefix": "DnD Tracker/"}) == "prefix=DnD%20Tracker%2F"


def test_canonical_query_sorts_by_key():
    assert canonical_query({"prefix": "a", "list-type": "2"}) == "list-type=2&prefix=a"


def test_canonical_request_has_the_spec_layout():
    creq = canonical_request(
        "GET", "/bucket", "list-type=2",
        {"host": "s3.test", "x-amz-date": "20240101T000000Z"},
        "abc123",
    )
    assert creq == (
        "GET\n"
        "/bucket\n"
        "list-type=2\n"
        "host:s3.test\n"
        "x-amz-date:20240101T000000Z\n"
        "\n"                       # blank line between headers and signed list
        "host;x-amz-date\n"
        "abc123"
    )


def test_s3_object_keys_mirror_the_folder_layout():
    store = S3Storage("mybucket", "AK", "SK", prefix="dnd")
    # Encounters at the top of the prefix, everything else in a named folder,
    # so a bucket and a synced folder hold the same shape.
    assert store._object_key("encounters", "fight.json") == "dnd/fight.json"
    assert store._object_key("spells", "shield.json") == "dnd/spells/shield.json"
    assert store._collection_prefix("spells") == "dnd/spells/"


def test_s3_without_a_prefix_puts_encounters_at_the_root():
    store = S3Storage("mybucket", "AK", "SK")
    assert store._object_key("encounters", "fight.json") == "fight.json"
    assert store._collection_prefix("encounters") == ""


def test_s3_defaults_the_endpoint_to_amazon_for_the_region():
    assert S3Storage("b", "AK", "SK", region="eu-west-2").endpoint == (
        "https://s3.eu-west-2.amazonaws.com"
    )
    # R2/B2/MinIO supply their own and it must win.
    assert S3Storage("b", "AK", "SK", endpoint="http://minio:9000/").endpoint == (
        "http://minio:9000"
    )


def test_s3_requires_credentials():
    with pytest.raises(ValueError):
        S3Storage("bucket", "", "")


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

def test_every_provider_builds_from_its_own_declared_fields():
    """The settings dialog renders from `fields` alone, so a field a provider
    needs but does not declare is invisible in the UI and impossible to set."""
    samples = {
        "webdav": {"url": "https://c.test/dav", "username": "alice"},
        "s3": {"bucket": "b", "access_key": "AK", "secret_key": "SK"},
        "http": {"url": "http://s.test:8000"},
    }
    for provider in providers.PROVIDERS:
        if provider.group != providers.SERVICE:
            continue
        values = samples[provider.id]
        assert not providers.missing_fields(provider.id, values)
        backend = providers.build(provider.id, values)
        assert backend.provider_id == provider.id


def test_folder_providers_all_produce_a_folder_backend(tmp_path):
    for provider in providers.PROVIDERS:
        if provider.group != providers.FOLDER:
            continue
        backend = providers.build(provider.id, {"path": str(tmp_path / provider.id)})
        assert isinstance(backend, FolderStorage)
        # The id is carried through, so a status line can say "Dropbox".
        assert backend.provider_id == provider.id


def test_missing_required_fields_are_reported_by_label():
    assert providers.missing_fields("s3", {"bucket": "b"}) == [
        "Access key ID", "Secret access key",
    ]
    # Optional fields never appear.
    assert providers.missing_fields("webdav", {"url": "u", "username": "a"}) == []


def test_build_refuses_rather_than_half_configuring():
    with pytest.raises(ValueError, match="Secret access key"):
        providers.build("s3", {"bucket": "b", "access_key": "AK"})
    with pytest.raises(ValueError, match="Unknown storage provider"):
        providers.build("carrier_pigeon", {})


def test_provider_ids_are_unique_and_stable():
    ids = providers.ids()
    assert len(ids) == len(set(ids))
    # These are written into settings.json; renaming one strands installs.
    assert set(ids) >= {"local", "dropbox", "google_drive", "onedrive",
                        "icloud", "webdav", "s3", "http"}


def test_a_cloud_provider_refuses_to_invent_its_sync_root(tmp_path):
    """Creating ~/Dropbox/DnD Tracker on a machine with no Dropbox yields a
    plain directory that looks synced, never syncs, and quietly strands the
    library on one machine. Refusing is the only safe answer."""
    absent = tmp_path / "no-such-dropbox" / "DnD Tracker"
    with pytest.raises(ValueError, match="does not appear to be set up"):
        providers.build("dropbox", {"path": str(absent)})


def test_a_cloud_provider_accepts_a_folder_whose_root_exists(tmp_path):
    (tmp_path / "Dropbox").mkdir()
    backend = providers.build("dropbox", {"path": str(tmp_path / "Dropbox" / "DnD")})
    assert os.path.isdir(backend.data_dir)


def test_the_local_provider_may_create_the_folder_it_is_given(tmp_path):
    """Unlike a sync root, a folder on this computer is the user's to make."""
    backend = providers.build("local", {"path": str(tmp_path / "fresh" / "lib")})
    assert os.path.isdir(backend.data_dir)
