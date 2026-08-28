"""
The one interface every storage provider implements.

Every backend the app can talk to -- a folder on disk, a folder Dropbox keeps
in sync, a WebDAV share, an S3 bucket, an HTTP service -- is the same shape: a
JSON blob store keyed by filename, in four collections. So that is all a
provider has to implement. The four primitives below are the entire contract:

    _list(collection)            -> ["goblin.json", ...]
    _read(collection, key)       -> dict, or None when it isn't there
    _write(collection, key, obj) -> None
    _delete(collection, key)     -> None

Everything the app actually calls -- `list()`, `get_statblock()`,
`save_spell()`, all sixteen of them -- is derived here, once. A new provider is
a class with four short methods and an entry in `providers.py`; it does not get
to invent its own spelling of "save a spell", which is what kept the previous
two backends in step only by hand and by luck.

`_read` returning None means *absent*, and only absent. A provider that cannot
reach its storage must raise -- an unreachable server that answers None reads
to the app as an empty library, and the app will happily save over it.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from app.creature import CustomEncoder
from app import settings_sync

# The four namespaces the app stores things in. "encounters" is the default
# one -- it also holds the player roster, the autosaved combat state, the PC
# group rosters and the synced-settings blob.
ENCOUNTERS = "encounters"
STATBLOCKS = "statblocks"
SPELLS = "spells"
ITEMS = "items"

COLLECTIONS = (ENCOUNTERS, STATBLOCKS, SPELLS, ITEMS)


def to_plain_json(obj: Any) -> Any:
    """Dataclasses and enums down to dicts, lists and scalars.

    The app hands storage `I_Creature`s and `Condition`s, which no transport
    can serialise on its own. Doing it here means a provider only ever sees
    plain JSON types and never needs to know about `CustomEncoder`.
    """
    return json.loads(json.dumps(obj, cls=CustomEncoder, ensure_ascii=False))


class StorageBackend(ABC):
    """Base class for every storage provider.

    Subclasses implement the four primitives and set `provider_id`. They may
    override `describe()` and `check()`; the rest is inherited.
    """

    #: matches the id in providers.PROVIDERS
    provider_id: str = ""

    #: shown in dialogs and the log -- "the folder ~/Dropbox/DnD Tracker"
    location: str = ""

    # ---- the contract ----

    @abstractmethod
    def _list(self, collection: str) -> List[str]:
        """Keys in `collection`, sorted. Empty list if the collection is new."""

    @abstractmethod
    def _read(self, collection: str, key: str) -> Optional[dict]:
        """The object, or None if it does not exist. Raise if unreachable."""

    @abstractmethod
    def _write(self, collection: str, key: str, data: Any) -> None:
        """Store `data` (already plain JSON) under `key`."""

    @abstractmethod
    def _delete(self, collection: str, key: str) -> None:
        """Remove `key`. Deleting something absent is not an error."""

    # ---- optional, with workable defaults ----

    def describe(self) -> str:
        """One line naming where this backend puts things."""
        return self.location or self.provider_id or "storage"

    def check(self) -> str:
        """Prove the backend is usable, or raise with a reason.

        Listing is the cheapest operation that exercises the whole path --
        address, credentials, permissions -- so "Test Connection" is a list.
        """
        keys = self._list(ENCOUNTERS)
        return f"Connected. {len(keys)} encounter(s) found."

    # ---- Encounters ----

    def list(self) -> List[str]:
        # The synced-settings blob shares this namespace, so it is filtered
        # here rather than in each of the four callers that would otherwise
        # offer it as an encounter to load or delete.
        return [k for k in self._list(ENCOUNTERS) if k != settings_sync.REMOTE_KEY]

    def get(self, key: str) -> Optional[dict]:
        return self._read(ENCOUNTERS, key)

    def put(self, key: str, data: Any) -> None:
        self._write(ENCOUNTERS, key, to_plain_json(data))

    def delete(self, key: str) -> None:
        self._delete(ENCOUNTERS, key)

    def put_json(self, key: str, obj: dict) -> None:
        self.put(key, obj)

    def get_json(self, key: str) -> Optional[dict]:
        return self.get(key)

    # ---- Statblocks ----

    def list_statblock_keys(self) -> List[str]:
        return self._list(STATBLOCKS)

    def get_statblock(self, key: str) -> Optional[dict]:
        return self._read(STATBLOCKS, key)

    def save_statblock(self, key: str, data: dict) -> bool:
        self._write(STATBLOCKS, key, to_plain_json(data))
        return True

    def delete_statblock(self, key: str) -> bool:
        self._delete(STATBLOCKS, key)
        return True

    # ---- Spells ----

    def list_spell_keys(self) -> List[str]:
        return self._list(SPELLS)

    def get_spell(self, key: str) -> Optional[dict]:
        return self._read(SPELLS, key)

    def save_spell(self, key: str, data: dict) -> bool:
        self._write(SPELLS, key, to_plain_json(data))
        return True

    def delete_spell(self, key: str) -> bool:
        self._delete(SPELLS, key)
        return True

    # ---- Items ----

    def list_item_keys(self) -> List[str]:
        return self._list(ITEMS)

    def get_item(self, key: str) -> Optional[dict]:
        return self._read(ITEMS, key)

    def save_item(self, key: str, data: dict) -> bool:
        self._write(ITEMS, key, to_plain_json(data))
        return True

    def delete_item(self, key: str) -> bool:
        self._delete(ITEMS, key)
        return True
