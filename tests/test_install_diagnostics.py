"""Help → Installation Details, and the startup log line behind it.

The point of these is that "updating doesn't work" arrives with the answer
attached. Each check can_self_update() makes has to be visible individually,
because knowing *which* one failed is the whole of what makes it actionable.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app import install_diagnostics, install_layout  # noqa: E402


@pytest.fixture
def frozen(monkeypatch):
    """Pretend to be a packaged build running from wherever the test says."""
    def _at(path):
        monkeypatch.setattr(install_layout, "running_frozen", lambda: True)
        monkeypatch.setattr(install_layout, "running_dir", lambda: str(path))
    return _at


def _versioned(root, launcher=True, version="0.4.2"):
    v = root / "versions" / version
    v.mkdir(parents=True)
    (v / install_layout.app_binary_name()).write_text("app")
    if launcher:
        (root / install_layout.launcher_binary_name()).write_text("launcher")
    (root / "current").write_text(version + "\n")
    return v


def _values(rows):
    return dict(rows)


def test_healthy_install_reports_it_can_update(tmp_path, frozen):
    frozen(_versioned(tmp_path))
    v = _values(install_diagnostics.collect())
    assert v["Can install updates"] == "yes"
    assert v["Install root"] == str(tmp_path)
    assert v["Running version"] == "0.4.2"
    assert v["Install root writable"] == "yes"
    assert "Reason" not in v


def test_missing_launcher_is_visible_as_its_own_row(tmp_path, frozen):
    """Not just "no" with a sentence -- the failing check itself."""
    frozen(_versioned(tmp_path, launcher=False))
    v = _values(install_diagnostics.collect())
    assert v["Can install updates"] == "no"
    assert v[f"Launcher present ({install_layout.launcher_binary_name()})"] == "no"
    assert "launcher is missing" in v["Reason"]


def test_read_only_install_root_is_visible(tmp_path, frozen):
    """The Windows case: extracted into somewhere like C:\\Program Files."""
    version_dir = _versioned(tmp_path)
    frozen(version_dir)
    os.chmod(tmp_path, 0o555)
    try:
        v = _values(install_diagnostics.collect())
        assert v["Install root writable"] == "no"
        assert v["Can install updates"] == "no"
        assert "permission" in v["Reason"].lower()
    finally:
        os.chmod(tmp_path, 0o755)


def test_flat_install_says_so(tmp_path, frozen):
    (tmp_path / install_layout.app_binary_name()).write_text("app")
    frozen(tmp_path)
    v = _values(install_diagnostics.collect())
    assert v["Install layout"] == "not a versioned install"
    assert v["Can install updates"] == "no"


def test_collect_never_raises_in_a_source_checkout():
    """It runs at startup, before any window exists -- it must not be able to
    stop the app from starting."""
    rows = install_diagnostics.collect()
    assert rows
    assert all(isinstance(a, str) and isinstance(b, str) for a, b in rows)


def test_as_text_is_aligned_and_complete(tmp_path, frozen):
    frozen(_versioned(tmp_path))
    text = install_diagnostics.as_text()
    assert "Can install updates" in text
    assert str(tmp_path) in text
    assert len(text.splitlines()) == len(install_diagnostics.collect())


def test_log_summary_is_one_line_when_healthy(tmp_path, frozen):
    frozen(_versioned(tmp_path))
    lines = []
    install_diagnostics.log_summary(lines.append)
    assert lines == ["[Install] Updates can be installed in place."]


def test_log_summary_dumps_the_detail_when_it_cannot(tmp_path, frozen):
    """The log is read precisely when the answer is no."""
    frozen(_versioned(tmp_path, launcher=False))
    lines = []
    install_diagnostics.log_summary(lines.append)
    assert len(lines) > 1
    assert any("cannot be installed in place" in line for line in lines)
    assert any("Launcher present" in line for line in lines)


def test_log_summary_survives_a_broken_check(monkeypatch):
    def boom():
        raise RuntimeError("nope")
    monkeypatch.setattr(install_layout, "can_self_update", boom)
    lines = []
    install_diagnostics.log_summary(lines.append)
    assert any("[WARN]" in line for line in lines)
