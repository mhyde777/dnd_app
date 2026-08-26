import os
from dotenv import load_dotenv

import app.settings as _settings
from app.paths import config_dir as _config_dir, config_path as _config_path


def get_config_dir() -> str:
    return _config_dir()

def get_config_path(filename: str) -> str:
    return _config_path(filename)

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

# ---- Bridge configuration ----
#
# Every bridge value follows the same precedence: a settings.json key (written
# by the GUI), then the matching environment variable, then a default. The
# settings key is the env name lowercased, so BRIDGE_URL <-> "bridge_url".
# Keeping .env working means existing installs are untouched, while a new user
# configures everything from the Settings dialog and never learns .env exists.


def bridge_value(env_name: str, default: str = "") -> str:
    configured = _settings.get(env_name.lower())
    if configured not in (None, ""):
        return str(configured).strip()
    return os.getenv(env_name, "").strip() or default


def bridge_flag(env_name: str, default: bool) -> bool:
    configured = _settings.get(env_name.lower())
    if configured is not None:
        return bool(configured)
    raw = os.getenv(env_name, "").strip()
    if raw == "":
        return default
    return raw not in ("0", "false", "False")


def foundry_bridge_enabled() -> bool:
    """Master switch for all Foundry sync.

    Off unless asked for, and it gates the settings UI as well as the runtime:
    someone who does not use Foundry should never be shown a bridge URL and a
    shared secret and have to wonder what they are for.

    Defaults on for anyone whose .env already configures a bridge, so existing
    installs keep working without visiting the dialog.
    """
    configured = _settings.get("foundry_bridge_enabled")
    if configured is not None:
        return bool(configured)
    return bool(os.getenv("BRIDGE_TOKEN", "").strip())


# ---- Feature flags ----

def local_bridge_enabled() -> bool:  # noqa: D401
    """Whether to start the in-process bridge server.

    Off unless asked for. It binds a port and invents a token when none is set,
    which is fine on a machine running Foundry and wrong on everyone else's --
    so a fresh install starts nothing until the user opts in. An existing .env
    still wins, so setups that predate the settings key keep working.
    """
    if not foundry_bridge_enabled():
        return False
    return bridge_flag("LOCAL_BRIDGE_ENABLED", False)

def update_check_enabled() -> bool:
    """Whether to ask GitHub about newer releases on startup.

    On by default so a distributed build tells people about fixes, but a
    single settings key or env var turns it off for anyone who would rather
    the app made no network calls of its own.
    """
    configured = _settings.get("update_check_enabled")
    if configured is not None:
        return bool(configured)
    return os.getenv("UPDATE_CHECK_ENABLED", "1").strip() not in ("", "0", "false", "False")


def bridge_stream_enabled() -> bool:
    return bridge_flag("BRIDGE_STREAM_ENABLED", True)


# ---- Local bridge ----
#
# The in-process bridge is the whole Foundry story for someone running both
# programs on one PC. It has to work with no terminal, no .env and no reverse
# proxy, so everything it needs is derived here and written back to
# settings.json -- the GUI shows what was chosen rather than asking for it.


LOCAL_BRIDGE_DEFAULT_PORT = 8787


def local_bridge_lan() -> bool:
    """Whether the local bridge should accept connections from the network.

    Off by default: bound to loopback the bridge is reachable only by programs
    on this machine, which is what "Foundry is on this PC" needs. Someone whose
    Foundry runs on a different box ticks this and gets 0.0.0.0 instead.
    """
    return bridge_flag("LOCAL_BRIDGE_LAN", False)


def local_bridge_host() -> str:
    """The address the in-process bridge binds.

    An explicitly configured host always wins; otherwise the LAN switch picks
    between loopback and every interface.
    """
    configured = bridge_value("LOCAL_BRIDGE_HOST") or bridge_value("BRIDGE_HOST")
    if configured:
        return configured
    return "0.0.0.0" if local_bridge_lan() else "127.0.0.1"


def local_bridge_port() -> int:
    raw = bridge_value("LOCAL_BRIDGE_PORT") or bridge_value("BRIDGE_PORT")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return LOCAL_BRIDGE_DEFAULT_PORT


def ensure_bridge_secret() -> str:
    """The shared secret, minting and persisting one the first time.

    A secret nobody chose is still a secret worth having: the bridge listens on
    a port that any program on this machine -- and any web page the user
    visits, since a browser will happily POST to 127.0.0.1 -- can reach. The
    generated value costs the user one paste into Foundry and closes that off.

    Returns the existing secret untouched if there is one, so this is safe to
    call on every startup.
    """
    existing = bridge_value("BRIDGE_TOKEN")
    if existing:
        return existing
    import secrets as _secrets

    token = _secrets.token_hex(16)
    _settings.update({"bridge_token": token, "bridge_ingest_secret": token})
    return token
