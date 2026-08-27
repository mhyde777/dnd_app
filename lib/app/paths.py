"""
Where the application keeps its per-user state.

One definition, imported by everything that needs it. It used to be spelled out
separately in settings.py, config.py and app_log.py, which meant there was no
single place to redirect -- and no way to run against a throwaway profile.

`DND_TRACKER_CONFIG_DIR` overrides the location. That is what makes the
first-run experience testable: point it at an empty directory and the app
behaves exactly like a fresh install, without touching your real settings,
logs or data.

    DND_TRACKER_CONFIG_DIR=/tmp/profile pipenv run python main.py

This module imports nothing from the rest of the app, so it can sit underneath
settings, config and logging without a cycle.
"""
from __future__ import annotations

import os

ENV_VAR = "DND_TRACKER_CONFIG_DIR"
DEFAULT_CONFIG_DIR = os.path.join("~", ".dnd_tracker_config")


def config_dir() -> str:
    """The config directory for this run, expanded to an absolute path."""
    override = os.environ.get(ENV_VAR, "").strip()
    return os.path.abspath(os.path.expanduser(override or DEFAULT_CONFIG_DIR))


def config_path(*parts: str) -> str:
    """A path inside the config directory."""
    return os.path.join(config_dir(), *parts)


