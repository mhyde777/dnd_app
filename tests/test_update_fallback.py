"""A failed update must be visible, and must not be offered straight back.

The regression: 0.6.2's Linux build died before its window opened. The
launcher fell back to 0.6.1 as designed -- but silently, so "Update and
restart" looked like it just closed the app, and 0.6.1 then offered 0.6.2
again. The user clicked it again, and the loop repeated.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "lib"))
sys.path.insert(0, REPO_ROOT)

import launcher  # noqa: E402
from app import install_layout, update_check  # noqa: E402


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    from app import settings

    monkeypatch.setattr(settings, "_cache", None, raising=False)
    monkeypatch.setattr(settings, "settings_path", lambda: str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "config_dir", lambda: str(tmp_path), raising=False)
    yield settings
    settings._cache = None


@pytest.fixture
def root(tmp_path):
    """An install with 0.6.1 and 0.6.2, where 0.6.2 is current."""
    root = tmp_path / "install"
    for version in ("0.6.1", "0.6.2"):
        (root / "versions" / version).mkdir(parents=True)
        (root / "versions" / version / "combat_tracker").write_text("#!/bin/sh\n")
    (root / "current").write_text("0.6.2\n")
    return root


def _launch(root):
    """What the real launcher does before exec: pick a version, mark, log."""
    version = launcher.choose_version(str(root))
    (root / "launching").write_text(version + "\n")
    launcher.log(str(root), f"starting {version}")
    return version


def test_the_launch_after_a_fallback_reports_the_failed_version(root):
    assert _launch(root) == "0.6.2"          # 0.6.2 never clears `launching`...
    assert _launch(root) == "0.6.1"          # ...so the next start falls back

    layout = install_layout.Layout(root=str(root), version="0.6.1")
    assert install_layout.detect_fallback(layout) == "0.6.2"


def test_it_goes_away_on_the_next_ordinary_start(root):
    _launch(root)
    _launch(root)
    (root / "launching").unlink()            # 0.6.1's window came up
    _launch(root)

    layout = install_layout.Layout(root=str(root), version="0.6.1")
    assert install_layout.detect_fallback(layout) is None


def test_an_ordinary_start_is_not_a_fallback(root):
    _launch(root)
    layout = install_layout.Layout(root=str(root), version="0.6.2")
    assert install_layout.detect_fallback(layout) is None


def test_no_launcher_log_is_not_a_fallback(root):
    layout = install_layout.Layout(root=str(root), version="0.6.1")
    assert install_layout.detect_fallback(layout) is None


def test_a_fallback_to_some_other_version_is_not_ours(root):
    _launch(root)
    _launch(root)
    layout = install_layout.Layout(root=str(root), version="0.6.3")
    assert install_layout.detect_fallback(layout) is None


def test_the_failed_version_is_held_back_but_a_newer_one_is_not(isolated_settings):
    isolated_settings.set(install_layout.FAILED_VERSION_KEY, "0.6.2")
    assert update_check.failed_here("v0.6.2")
    assert update_check.failed_here("0.6.2")
    assert not update_check.failed_here("v0.6.3")


def test_nothing_is_held_back_when_nothing_failed(isolated_settings):
    assert not update_check.failed_here("v0.6.2")


def test_the_startup_check_stays_quiet_about_the_failed_version(isolated_settings, monkeypatch):
    isolated_settings.set(install_layout.FAILED_VERSION_KEY, "0.6.2")
    monkeypatch.setattr(update_check, "fetch_latest_version", lambda url=None: "0.6.2")
    monkeypatch.setattr(update_check, "is_newer", lambda v, current=None: True)
    offered = []
    update_check.check_in_background(offered.append).join(timeout=5)
    assert offered == []

    monkeypatch.setattr(update_check, "fetch_latest_version", lambda url=None: "0.6.3")
    update_check.check_in_background(offered.append).join(timeout=5)
    assert offered == ["0.6.3"]
