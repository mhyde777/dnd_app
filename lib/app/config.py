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

def player_view_enabled() -> bool:
    v = _settings.get("player_view_enabled")
    if v is not None:
        return bool(v)
    return os.getenv("PLAYER_VIEW_ENABLED", "0").strip() not in ("", "0", "false", "False")

def local_bridge_enabled() -> bool:
    return os.getenv("LOCAL_BRIDGE_ENABLED", "1").strip() not in ("", "0", "false", "False")

def bridge_stream_enabled() -> bool:
    return os.getenv("BRIDGE_STREAM_ENABLED", "1").strip() not in ("", "0", "false", "False")

# ---- Foundry Direct (socket.io) config ----

def get_bridge_mode() -> str:
    """
    Returns the active bridge mode:
      "disabled"       - no Foundry sync
      "local"          - local bridge server (Foundry on same machine)
      "http_bridge"    - remote HTTP bridge service (requires tunnel)
      "foundry_socket" - direct socket.io connection to remote Foundry
    """
    mode = _settings.get("bridge_mode")
    if mode in ("disabled", "local", "http_bridge", "foundry_socket"):
        return mode
    # Legacy: if BRIDGE_TOKEN is set in env, treat as http_bridge
    if os.getenv("BRIDGE_TOKEN", "").strip():
        return "http_bridge"
    return "local"

def get_foundry_url() -> str:
    return (_settings.get("foundry_url") or os.getenv("FOUNDRY_URL", "")).rstrip("/")

def get_foundry_username() -> str:
    return _settings.get("foundry_username") or os.getenv("FOUNDRY_USERNAME", "Gamemaster")

def get_foundry_password() -> str:
    return _settings.get("foundry_password") or os.getenv("FOUNDRY_PASSWORD", "")

def get_foundry_user_id() -> str:
    """Foundry user UUID — required for Foundry v13+, optional for older versions."""
    return _settings.get("foundry_user_id") or os.getenv("FOUNDRY_USER_ID", "")
