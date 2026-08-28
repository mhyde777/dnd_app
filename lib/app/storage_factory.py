"""
Which storage provider this install uses.

app.py and the maintenance scripts all have to answer the same question --
"where does this install keep its library?" -- and they had drifted: the
scripts refused to run unless a data directory was set explicitly, while the
app happily fell back to the config directory. Same install, two answers.

Import this rather than reconstructing the choice. There is no branching here
any more: the provider registry says how to build each backend, so adding a
provider never means editing this file.
"""
from __future__ import annotations

from typing import Optional, Tuple

from app.config import get_storage_config, get_storage_provider
from app.storage import providers
from app.storage.base import StorageBackend


def open_storage() -> Tuple[Optional[StorageBackend], Optional[str]]:
    """The configured backend, or (None, reason) when it cannot be built.

    Every backend presents the same interface, so callers do not need to know
    which one they got. The reason is written for a user to read in a dialog,
    not for a log.
    """
    provider_id = get_storage_provider()
    try:
        return providers.build(provider_id, get_storage_config(provider_id)), None
    except Exception as exc:
        return None, (
            f"Could not open your storage ({providers.label(provider_id)}).\n\n"
            f"{exc}\n\n"
            "Go to File → Settings → Storage to fix it."
        )
