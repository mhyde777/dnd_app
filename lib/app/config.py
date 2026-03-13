import os
from dotenv import load_dotenv

import app.settings as _settings

CONFIG_DIR = os.path.expanduser("~/.dnd_tracker_config")

def get_config_dir() -> str:
    return CONFIG_DIR

def get_config_path(filename: str) -> str:
    return os.path.join(CONFIG_DIR, filename)

load_dotenv(get_config_path(".env"), override=False)

TOKEN_PATH = get_config_path("token.json")

# ---- Storage config ----

def get_storage_api_key() -> str:
    return _settings.get("storage_api_key") or os.getenv("STORAGE_API_KEY", "").strip()

def get_storage_api_base() -> str:
    return (_settings.get("storage_api_base") or os.getenv("STORAGE_API_BASE", "")).rstrip("/")

def use_storage_api_only() -> bool:
    mode = _settings.get("storage_mode")
    if mode is not None:
        return mode == "api"
    return os.getenv("USE_STORAGE_API_ONLY", "0").strip() not in ("", "0", "false", "False")

def get_local_data_dir() -> str:
    """User-configured local data directory (empty = use default)."""
    return _settings.get("local_data_dir") or os.getenv("LOCAL_DATA_DIR", "")

# ---- Feature flags ----

def local_bridge_enabled() -> bool:
    return os.getenv("LOCAL_BRIDGE_ENABLED", "1").strip() not in ("", "0", "false", "False")

def bridge_stream_enabled() -> bool:
    return os.getenv("BRIDGE_STREAM_ENABLED", "1").strip() not in ("", "0", "false", "False")
