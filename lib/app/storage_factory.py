"""
Which storage backend this install uses.

app.py and the maintenance scripts all have to answer the same question --
"remote API or local files, and where?" -- and they had drifted: the scripts
refused to run unless `local_data_dir` was set explicitly, while the app
happily fell back to the config directory. Same install, two answers.

Import this rather than reconstructing the choice.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from app.config import (
    get_config_path,
    get_local_data_dir,
    get_storage_api_base,
    use_storage_api_only,
)

MISSING_API_URL = (
    "Remote API mode is enabled, but no API URL is configured.\n\n"
    "Go to File → Settings to set your API URL, or switch to Local Files mode."
)


def open_storage() -> Tuple[Optional[Any], Optional[str]]:
    """The configured backend, or (None, reason) when it cannot be built.

    The two backends share an interface (see StorageAPI and LocalStorage), so
    callers do not need to know which one they got.
    """
    if use_storage_api_only():
        base = get_storage_api_base()
        if not base:
            return None, MISSING_API_URL
        from app.storage_api import StorageAPI
        return StorageAPI(base), None

    from app.local_storage import LocalStorage
    return LocalStorage(get_local_data_dir() or get_config_path("data")), None
