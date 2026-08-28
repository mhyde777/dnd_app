"""
The list of places the library can live.

This registry is the single description of every storage provider: what to call
it, what it needs to be told, and how to build it. The settings dialog renders
its form from `fields` and knows nothing about any particular provider; the
factory calls `build` and knows nothing either. Adding a provider is this file
plus a backend class -- no UI code, no branching in `open_storage()`.

Two groups, because they answer different questions:

  folder   A directory this machine can see. "This computer" is one; so are
           Dropbox, Google Drive, OneDrive and iCloud, which are directories
           that a sync client mirrors to a service. All of them are
           `FolderStorage` -- what differs is where the folder is and what to
           call it, which is exactly what a registry entry is for.

  service  Something reached over the network with credentials: WebDAV, an
           S3-compatible bucket, an HTTP storage server. No sync client
           involved, and nothing stored on this machine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from app import paths
from app.storage import cloud_folders
from app.storage.base import StorageBackend
from app.storage.folder import FolderStorage
from app.storage.http import HttpStorage
from app.storage.s3 import S3Storage
from app.storage.webdav import WebDavStorage

FOLDER = "folder"
SERVICE = "service"


@dataclass(frozen=True)
class Field:
    """One input on the settings form."""

    key: str
    label: str
    kind: str = "text"          # text | password | folder | url
    placeholder: str = ""
    required: bool = True
    help: str = ""


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    group: str
    summary: str
    fields: Tuple[Field, ...]
    build: Callable[[Dict[str, Any]], StorageBackend]
    #: Shown under the form. Use for caveats the user should read *before*
    #: committing their library to this provider.
    caution: str = ""


# The caveat that applies to every folder a sync client watches. It is real and
# it loses data, so it is stated on each of them rather than buried in a doc.
_SYNC_CAUTION = (
    "Don't run the tracker on two machines at once against this folder — the "
    "sync client has no way to merge two versions of an encounter, and one "
    "machine's save will win. Use a service provider below if you need that."
)


def _folder_path(config: Dict[str, Any], provider_id: str) -> str:
    """The configured folder, falling back to the suggested one."""
    configured = (config.get("path") or "").strip()
    if configured:
        return configured
    if provider_id == "local":
        return paths.config_path("data")
    suggested = cloud_folders.suggested_path(provider_id)
    if not suggested:
        raise ValueError(
            "No folder is set, and this computer's folder for this service "
            "could not be found. Choose one with Browse."
        )
    return suggested


def _build_folder(provider_id: str) -> Callable[[Dict[str, Any]], StorageBackend]:
    def build(config: Dict[str, Any]) -> StorageBackend:
        path = _folder_path(config, provider_id)
        if provider_id != "local":
            # FolderStorage creates what it is given, which is right for a
            # folder the user chose and wrong for a sync root that isn't
            # there: making ~/Dropbox/DnD Tracker on a machine with no
            # Dropbox produces an ordinary directory that looks like it is
            # syncing and never will, and the library silently stays on one
            # machine. Refuse instead, and say what to do about it.
            parent = os.path.dirname(os.path.abspath(os.path.expanduser(path)))
            if not os.path.isdir(parent):
                raise ValueError(
                    f"{label(provider_id)} does not appear to be set up on this "
                    f"computer -- {parent} does not exist. Install it and sign "
                    "in, or use Browse to pick the folder yourself."
                )
        return FolderStorage(path, provider_id)
    return build


def _build_webdav(config: Dict[str, Any]) -> StorageBackend:
    return WebDavStorage(
        base_url=(config.get("url") or "").strip(),
        username=(config.get("username") or "").strip(),
        password=config.get("password") or "",
        folder=(config.get("folder") or "").strip(),
    )


def _build_s3(config: Dict[str, Any]) -> StorageBackend:
    return S3Storage(
        bucket=(config.get("bucket") or "").strip(),
        access_key=(config.get("access_key") or "").strip(),
        secret_key=config.get("secret_key") or "",
        region=(config.get("region") or "us-east-1").strip(),
        endpoint=(config.get("endpoint") or "").strip(),
        prefix=(config.get("prefix") or "").strip(),
    )


def _build_http(config: Dict[str, Any]) -> StorageBackend:
    return HttpStorage(
        base_url=(config.get("url") or "").strip(),
        api_key=config.get("api_key") or "",
    )


_FOLDER_FIELD = Field(
    key="path",
    label="Folder",
    kind="folder",
    required=False,
    help="Leave blank to use the suggested location.",
)


PROVIDERS: Tuple[Provider, ...] = (
    Provider(
        id="local",
        label="This computer",
        group=FOLDER,
        summary=(
            "Plain JSON files in a folder on this machine. No network, nothing "
            "to keep running. Choose this unless you have a reason not to."
        ),
        fields=(_FOLDER_FIELD,),
        build=_build_folder("local"),
    ),
    Provider(
        id="dropbox",
        label="Dropbox",
        group=FOLDER,
        summary=(
            "A folder inside Dropbox, kept in sync by the Dropbox app. Nothing "
            "to authorise — if Dropbox is installed and signed in, this works."
        ),
        fields=(_FOLDER_FIELD,),
        build=_build_folder("dropbox"),
        caution=_SYNC_CAUTION,
    ),
    Provider(
        id="google_drive",
        label="Google Drive",
        group=FOLDER,
        summary=(
            "A folder inside Google Drive, kept in sync by Drive for Desktop. "
            "Install that first; Drive in a browser alone is not enough."
        ),
        fields=(_FOLDER_FIELD,),
        build=_build_folder("google_drive"),
        caution=_SYNC_CAUTION,
    ),
    Provider(
        id="onedrive",
        label="OneDrive",
        group=FOLDER,
        summary="A folder inside OneDrive, kept in sync by the OneDrive client.",
        fields=(_FOLDER_FIELD,),
        build=_build_folder("onedrive"),
        caution=_SYNC_CAUTION,
    ),
    Provider(
        id="icloud",
        label="iCloud Drive",
        group=FOLDER,
        summary="A folder inside iCloud Drive. macOS, or iCloud for Windows.",
        fields=(_FOLDER_FIELD,),
        build=_build_folder("icloud"),
        caution=_SYNC_CAUTION,
    ),
    Provider(
        id="webdav",
        label="WebDAV  (Nextcloud, ownCloud, Box, NAS)",
        group=SERVICE,
        summary=(
            "Any WebDAV share. No sync client needed — the app talks to the "
            "server directly, so several machines can share one library."
        ),
        fields=(
            Field("url", "Server URL", "url",
                  "https://cloud.example.com/remote.php/dav/files/alice"),
            Field("username", "Username"),
            Field("password", "Password", "password", required=False,
                  help="Use an app password if your provider offers one."),
            Field("folder", "Folder", placeholder="DnD Tracker", required=False),
        ),
        build=_build_webdav,
    ),
    Provider(
        id="s3",
        label="S3-compatible  (S3, R2, B2, MinIO)",
        group=SERVICE,
        summary=(
            "An object storage bucket. Cheap, shared between machines, and "
            "supported by most providers and self-hosted MinIO."
        ),
        fields=(
            Field("bucket", "Bucket"),
            Field("access_key", "Access key ID"),
            Field("secret_key", "Secret access key", "password"),
            Field("region", "Region", placeholder="us-east-1", required=False),
            Field("endpoint", "Endpoint URL", "url", required=False,
                  help="Blank for Amazon S3. Required for R2, B2 and MinIO."),
            Field("prefix", "Prefix", placeholder="dnd-tracker", required=False,
                  help="Optional folder inside the bucket."),
        ),
        build=_build_s3,
    ),
    Provider(
        id="http",
        label="HTTP server  (self-hosted)",
        group=SERVICE,
        summary=(
            "An HTTP service you run that speaks this app's storage endpoints. "
            "See storage_service/ in the repository for a reference server."
        ),
        fields=(
            Field("url", "Server URL", "url", "http://192.168.1.100:8000"),
            Field("api_key", "API key", "password", required=False),
        ),
        build=_build_http,
    ),
)

_BY_ID: Dict[str, Provider] = {p.id: p for p in PROVIDERS}

DEFAULT_PROVIDER_ID = "local"


def get(provider_id: str) -> Optional[Provider]:
    return _BY_ID.get(provider_id)


def ids() -> List[str]:
    return [p.id for p in PROVIDERS]


def label(provider_id: str) -> str:
    provider = get(provider_id)
    return provider.label if provider else provider_id


def missing_fields(provider_id: str, config: Dict[str, Any]) -> List[str]:
    """Required fields the user has left empty, by label."""
    provider = get(provider_id)
    if provider is None:
        return []
    return [
        f.label for f in provider.fields
        if f.required and not str(config.get(f.key) or "").strip()
    ]


def build(provider_id: str, config: Dict[str, Any]) -> StorageBackend:
    """Construct the backend for `provider_id`. Raises with a reason."""
    provider = get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown storage provider: {provider_id!r}")
    missing = missing_fields(provider_id, config)
    if missing:
        raise ValueError(
            f"{provider.label} needs: {', '.join(missing)}. "
            "Set them in File → Settings → Storage."
        )
    return provider.build(config)
