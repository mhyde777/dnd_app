"""
Reading the storage settings, including the shape they had before providers
existed.

Every install in the wild has `storage_mode` and friends, not
`storage_provider`. If this file fails, those installs open the app pointed at
the wrong library -- or at nothing.
"""
from __future__ import annotations

import importlib
import json
import os

import pytest


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A throwaway config directory, with settings and config freshly loaded.

    Both modules cache: settings holds the parsed file, config reads env at
    import. Reloading them is what makes each case independent.
    """
    monkeypatch.setenv("DND_TRACKER_CONFIG_DIR", str(tmp_path))
    for var in ("USE_STORAGE_API_ONLY", "STORAGE_API_BASE",
                "STORAGE_API_KEY", "LOCAL_DATA_DIR"):
        monkeypatch.delenv(var, raising=False)

    def load(settings_dict=None):
        if settings_dict is not None:
            (tmp_path / "settings.json").write_text(json.dumps(settings_dict))
        import app.settings as settings
        import app.config as config
        importlib.reload(settings)
        importlib.reload(config)
        return settings, config

    yield load

    # Leave the modules bound to the real profile for the rest of the suite.
    import app.settings as settings
    import app.config as config
    importlib.reload(settings)
    importlib.reload(config)


# --------------------------------------------------------------------------
# Legacy settings.json
# --------------------------------------------------------------------------

def test_old_api_mode_reads_as_the_http_provider(profile):
    _, config = profile({
        "storage_mode": "api",
        "storage_api_base": "http://192.168.1.100:8000/",
        "storage_api_key": "sekrit",
    })
    assert config.get_storage_provider() == "http"
    assert config.get_storage_config() == {
        "url": "http://192.168.1.100:8000",   # trailing slash stripped
        "api_key": "sekrit",
    }


def test_old_local_mode_reads_as_the_local_provider(profile):
    _, config = profile({"storage_mode": "local", "local_data_dir": "/srv/dnd"})
    assert config.get_storage_provider() == "local"
    assert config.get_storage_config() == {"path": "/srv/dnd"}
    assert config.get_local_data_dir() == "/srv/dnd"


def test_a_completely_empty_profile_defaults_to_local(profile):
    _, config = profile({})
    assert config.get_storage_provider() == "local"
    assert config.get_local_data_dir() == ""


def test_legacy_config_is_not_offered_to_a_different_provider(profile):
    """The old keys described exactly one backend. Handing an API URL to the
    Dropbox provider as though it were a folder would be nonsense."""
    _, config = profile({"storage_mode": "api", "storage_api_base": "http://x:8000"})
    assert config.get_storage_config("dropbox") == {}
    assert config.get_storage_config("http") == {"url": "http://x:8000", "api_key": ""}


# --------------------------------------------------------------------------
# Legacy environment variables (.env installs)
# --------------------------------------------------------------------------

def test_env_api_flag_still_selects_the_http_provider(profile, monkeypatch):
    monkeypatch.setenv("USE_STORAGE_API_ONLY", "1")
    monkeypatch.setenv("STORAGE_API_BASE", "http://env-server:8000")
    monkeypatch.setenv("STORAGE_API_KEY", "envkey")
    _, config = profile({})
    assert config.get_storage_provider() == "http"
    assert config.get_storage_config() == {
        "url": "http://env-server:8000", "api_key": "envkey",
    }


def test_env_local_data_dir_still_applies(profile, monkeypatch):
    monkeypatch.setenv("LOCAL_DATA_DIR", "/mnt/dnd")
    _, config = profile({})
    assert config.get_storage_provider() == "local"
    assert config.get_local_data_dir() == "/mnt/dnd"


# --------------------------------------------------------------------------
# The new shape
# --------------------------------------------------------------------------

def test_new_keys_win_over_the_legacy_ones(profile):
    _, config = profile({
        "storage_mode": "api",
        "storage_api_base": "http://old:8000",
        "storage_provider": "dropbox",
        "storage_config": {"dropbox": {"path": "/home/a/Dropbox/DnD"}},
    })
    assert config.get_storage_provider() == "dropbox"
    assert config.get_storage_config() == {"path": "/home/a/Dropbox/DnD"}


def test_each_provider_keeps_its_own_credentials(profile):
    """Comparing S3 against a Dropbox folder and going back must not cost you
    the bucket credentials you typed."""
    settings, config = profile({})
    config.set_storage_config("s3", {"bucket": "b", "access_key": "AK",
                                     "secret_key": "SK"})
    config.set_storage_config("dropbox", {"path": "/home/a/Dropbox/DnD"})

    assert config.get_storage_provider() == "dropbox"
    assert config.get_storage_config("s3")["bucket"] == "b"
    assert config.get_storage_config("dropbox")["path"] == "/home/a/Dropbox/DnD"


def test_get_local_data_dir_is_empty_for_network_providers(profile):
    """It feeds get_data_dir(), which must fall back rather than treat a URL
    as a filesystem path."""
    _, config = profile({
        "storage_provider": "s3",
        "storage_config": {"s3": {"bucket": "b"}},
    })
    assert config.get_local_data_dir() == ""


def test_migration_writes_the_new_keys_and_keeps_the_old(profile):
    settings, config = profile({
        "storage_mode": "api",
        "storage_api_base": "http://old:8000",
        "storage_api_key": "k",
        "panel_layout": {"left": ["controls"]},
    })
    assert config.migrate_legacy_storage() is True

    saved = json.loads(open(settings.settings_path()).read())
    assert saved["storage_provider"] == "http"
    assert saved["storage_config"]["http"] == {"url": "http://old:8000", "api_key": "k"}
    # The old keys stay, so downgrading to a previous build still works...
    assert saved["storage_mode"] == "api"
    # ...and unrelated settings are untouched.
    assert saved["panel_layout"] == {"left": ["controls"]}


def test_migration_is_idempotent(profile):
    _, config = profile({"storage_mode": "local", "local_data_dir": "/srv/dnd"})
    assert config.migrate_legacy_storage() is True
    assert config.migrate_legacy_storage() is False


def test_migration_does_nothing_on_a_fresh_profile(profile):
    _, config = profile({})
    assert config.migrate_legacy_storage() is False


def test_migration_never_overwrites_a_configured_provider(profile):
    _, config = profile({
        "storage_mode": "api",
        "storage_provider": "dropbox",
        "storage_config": {"dropbox": {"path": "/d"}},
    })
    assert config.migrate_legacy_storage() is False
    assert config.get_storage_provider() == "dropbox"


# --------------------------------------------------------------------------
# The factory
# --------------------------------------------------------------------------

def test_open_storage_builds_the_configured_provider(profile, tmp_path):
    _, config = profile({
        "storage_provider": "local",
        "storage_config": {"local": {"path": str(tmp_path / "lib")}},
    })
    import app.storage_factory as factory
    importlib.reload(factory)
    storage, problem = factory.open_storage()
    assert problem is None
    assert storage.describe() == str(tmp_path / "lib")


def test_open_storage_explains_itself_instead_of_raising(profile):
    _, config = profile({
        "storage_provider": "s3",
        "storage_config": {"s3": {"bucket": "b"}},   # no credentials
    })
    import app.storage_factory as factory
    importlib.reload(factory)
    storage, problem = factory.open_storage()
    # The app shows this in a dialog; it must name the provider and the fix.
    assert storage is None
    assert "S3" in problem and "Settings" in problem
