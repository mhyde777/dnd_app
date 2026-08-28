import os
from dotenv import load_dotenv

import app.settings as _settings
from app.paths import config_path as _config_path


def get_config_path(filename: str) -> str:
    return _config_path(filename)

load_dotenv(get_config_path(".env"), override=False)


# ---- Storage config ----
#
# Two settings keys describe storage:
#
#   storage_provider  the id of an entry in app.storage.providers.PROVIDERS
#   storage_config    {provider_id: {field: value}}
#
# Config is kept *per provider* rather than flat, so switching from S3 to a
# Dropbox folder and back does not lose the bucket credentials in between --
# the old shape had one set of fields for whichever mode was active, and
# changing your mind meant retyping them.
#
# Everything below also understands the previous shape (`storage_mode` of
# "local"/"api", plus storage_api_base / storage_api_key / local_data_dir, and
# the environment variables behind them). Existing installs therefore keep
# working untouched; they are rewritten to the new keys the next time the
# settings dialog is saved. See migrate_legacy_storage().

PROVIDER_KEY = "storage_provider"
CONFIG_KEY = "storage_config"

# Old settings/env keys, kept readable so nobody's .env stops working.
LEGACY_KEYS = (
    "storage_mode",
    "storage_api_base",
    "storage_api_key",
    "local_data_dir",
)


def _legacy_storage() -> tuple:
    """(provider_id, config) implied by the pre-provider settings and env."""
    mode = _settings.get("storage_mode")
    if mode is None:
        env_flag = os.getenv("USE_STORAGE_API_ONLY", "0").strip()
        mode = "api" if env_flag not in ("", "0", "false", "False") else "local"

    if mode == "api":
        return "http", {
            "url": (
                _settings.get("storage_api_base")
                or os.getenv("STORAGE_API_BASE", "")
            ).rstrip("/"),
            "api_key": (
                _settings.get("storage_api_key")
                or os.getenv("STORAGE_API_KEY", "")
            ).strip(),
        }
    return "local", {
        "path": _settings.get("local_data_dir") or os.getenv("LOCAL_DATA_DIR", "")
    }


def get_storage_provider() -> str:
    """The configured provider id."""
    configured = _settings.get(PROVIDER_KEY)
    if configured:
        return str(configured)
    return _legacy_storage()[0]


def get_storage_config(provider_id: str = "") -> dict:
    """The saved field values for a provider (the active one by default)."""
    provider_id = provider_id or get_storage_provider()
    stored = _settings.get(CONFIG_KEY) or {}
    if isinstance(stored, dict) and isinstance(stored.get(provider_id), dict):
        return dict(stored[provider_id])
    # Nothing saved under the new keys: fall back to the legacy shape, but only
    # for the provider it actually described.
    legacy_id, legacy_config = _legacy_storage()
    return dict(legacy_config) if legacy_id == provider_id else {}


def set_storage_config(provider_id: str, config: dict) -> None:
    """Save one provider's fields, leaving every other provider's alone."""
    stored = dict(_settings.get(CONFIG_KEY) or {})
    stored[provider_id] = dict(config)
    _settings.update({PROVIDER_KEY: provider_id, CONFIG_KEY: stored})


def migrate_legacy_storage() -> bool:
    """Write the old storage keys into the new shape, once.

    Returns True if anything was written. Safe to call on every startup: it
    does nothing once `storage_provider` exists, and it never removes the old
    keys -- an install that gets downgraded to a previous build still finds
    what it expects.
    """
    if _settings.get(PROVIDER_KEY):
        return False
    if not any(_settings.get(key) is not None for key in LEGACY_KEYS):
        return False
    provider_id, config = _legacy_storage()
    stored = dict(_settings.get(CONFIG_KEY) or {})
    stored.setdefault(provider_id, config)
    _settings.update({PROVIDER_KEY: provider_id, CONFIG_KEY: stored})
    return True


def get_local_data_dir() -> str:
    """The folder a folder-based provider uses (empty = the default)."""
    provider_id = get_storage_provider()
    from app.storage import providers as _providers

    provider = _providers.get(provider_id)
    if provider is None or provider.group != _providers.FOLDER:
        return ""
    return (get_storage_config(provider_id).get("path") or "").strip()

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
