"""
Storage providers: where the library of encounters, monsters, spells and items
lives.

Import order below is dependency order -- `providers` pulls in every backend
and `cloud_folders`, so those come first.
"""
from app.storage.base import (  # noqa: F401
    COLLECTIONS,
    ENCOUNTERS,
    ITEMS,
    SPELLS,
    STATBLOCKS,
    StorageBackend,
    to_plain_json,
)
from app.storage.folder import FolderStorage  # noqa: F401
from app.storage.http import HttpStorage  # noqa: F401
from app.storage.webdav import WebDavStorage  # noqa: F401
from app.storage.s3 import S3Storage  # noqa: F401
from app.storage import cloud_folders  # noqa: F401
from app.storage import providers  # noqa: F401

__all__ = [
    "COLLECTIONS",
    "ENCOUNTERS",
    "ITEMS",
    "SPELLS",
    "STATBLOCKS",
    "StorageBackend",
    "to_plain_json",
    "FolderStorage",
    "HttpStorage",
    "WebDavStorage",
    "S3Storage",
    "cloud_folders",
    "providers",
]
