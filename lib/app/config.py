import os
from dotenv import load_dotenv

CONFIG_DIR = os.path.expanduser("~/.dnd_tracker_config")

def get_config_dir() -> str:
    return CONFIG_DIR

def get_config_path(filename: str) -> str:
    return os.path.join(CONFIG_DIR, filename)

load_dotenv(get_config_path(".env"), override=False)

TOKEN_PATH = get_config_path("token.json")

# ---- Storage API config ----
def get_storage_api_key() -> str:
    return os.getenv("STORAGE_API_KEY", "").strip()
def get_storage_api_base() -> str:
    """
    Base URL for Storage API, e.g.:
      http://127.0.0.1:8000
      http://100.72.17.103:8000
    """
    return os.getenv("STORAGE_API_BASE", "").rstrip("/")

def use_storage_api_only() -> bool:
    """
    If set, use the Storage API and skip any local persistence fallbacks.
    """
    return os.getenv("USE_STORAGE_API_ONLY", "0").strip() not in ("", "0", "false", "False")


def player_view_enabled() -> bool:
    """
    If set, start the Player View HTTP server.
    """
    return os.getenv("PLAYER_VIEW_ENABLED", "0").strip() not in ("", "0", "false", "False")


def local_bridge_enabled() -> bool:
    """
    If set, start a local bridge server inside the app process.
    """
    return os.getenv("LOCAL_BRIDGE_ENABLED", "1").strip() not in ("", "0", "false", "False")


def bridge_stream_enabled() -> bool:
    """
    If set, use the bridge SSE stream instead of polling /state.
    """
    return os.getenv("BRIDGE_STREAM_ENABLED", "1").strip() not in ("", "0", "false", "False")
