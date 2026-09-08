"""The AppImage's self-install: does it produce a real, updatable install?

The point of the feature is that the easiest possible download (one file,
double-click) does not cost the user in-app updating. So the assertion that
matters most here is the round trip -- install_layout.detect() has to recognise
what appimage.install() writes, or the user has traded updates for convenience
without being told.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from app import appimage, install_layout  # noqa: E402


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    """Point HOME at a temp dir for every test in this module.

    install() writes a desktop entry to ~/.local/share/applications, and a test
    that does not redirect HOME writes it into the *real* one -- pointing at a
    tmp_path that pytest deletes on the way out. That left a second, iconless
    "Combat Tracker" in the applications menu that launched nothing, rewritten
    on every run of the suite. Autouse, because remembering per test is exactly
    what failed: six of the seven install() tests did not.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        os.path, "expanduser",
        lambda p: p.replace("~", str(home), 1) if p.startswith("~") else p,
    )
    return home


@pytest.fixture
def payload(tmp_path):
    """A stand-in for the AppImage's usr/bin: launcher, app binary, _internal."""
    src = tmp_path / "appdir" / "usr" / "bin"
    src.mkdir(parents=True)
    (src / install_layout.launcher_binary_name()).write_text("#!launcher\n")
    (src / install_layout.app_binary_name()).write_text("#!app\n")
    internal = src / "_internal"
    internal.mkdir()
    (internal / "base_library.zip").write_text("payload\n")
    (src / appimage.ICON_NAME).write_bytes(b"\x89PNG\r\n")
    return src


def test_detects_the_appimage_environment(monkeypatch):
    monkeypatch.setattr(appimage.sys, "platform", "linux")
    monkeypatch.setenv(appimage.ENV_APPIMAGE, "/home/u/Downloads/ct.AppImage")
    assert appimage.running_as_appimage() is True
    assert appimage.appimage_path() == "/home/u/Downloads/ct.AppImage"


def test_absent_outside_an_appimage(monkeypatch):
    monkeypatch.delenv(appimage.ENV_APPIMAGE, raising=False)
    assert appimage.running_as_appimage() is False


def test_not_an_appimage_on_windows(monkeypatch):
    """The env var could be inherited from a parent process; the format is
    Linux-only regardless."""
    monkeypatch.setattr(appimage.sys, "platform", "win32")
    monkeypatch.setenv(appimage.ENV_APPIMAGE, "/x/ct.AppImage")
    assert appimage.running_as_appimage() is False


def test_install_produces_a_layout_the_updater_recognises(tmp_path, payload):
    """The whole point: after installing, Help -> Check for Updates works."""
    root = tmp_path / "opt" / "combat-tracker"
    launcher = appimage.install("0.6.0", override=str(root), source=str(payload))

    assert Path(launcher) == root / install_layout.launcher_binary_name()
    assert os.access(launcher, os.X_OK)

    version_dir = root / install_layout.VERSIONS_DIRNAME / "0.6.0"
    layout = install_layout.detect(start=str(version_dir))
    assert layout is not None
    assert layout.root == str(root)
    assert layout.version == "0.6.0"
    assert layout.has_launcher()
    assert install_layout.read_current(layout) == "0.6.0"


def test_launcher_lives_at_the_root_not_in_the_version(tmp_path, payload):
    """It is the stable entry point an update must not replace."""
    root = tmp_path / "ct"
    appimage.install("0.6.0", override=str(root), source=str(payload))

    version_dir = root / install_layout.VERSIONS_DIRNAME / "0.6.0"
    assert (version_dir / install_layout.app_binary_name()).is_file()
    assert not (version_dir / install_layout.launcher_binary_name()).exists()
    assert (version_dir / "_internal" / "base_library.zip").is_file()


def test_app_binary_is_executable(tmp_path, payload):
    """copytree preserves mode, but the source came out of a squashfs image --
    worth asserting rather than assuming."""
    root = tmp_path / "ct"
    appimage.install("0.6.0", override=str(root), source=str(payload))
    inner = root / install_layout.VERSIONS_DIRNAME / "0.6.0" / install_layout.app_binary_name()
    assert os.access(inner, os.X_OK)


def test_refuses_a_payload_with_no_launcher(tmp_path, payload):
    (payload / install_layout.launcher_binary_name()).unlink()
    root = tmp_path / "ct"
    with pytest.raises(RuntimeError, match="launcher|combat-tracker"):
        appimage.install("0.6.0", override=str(root), source=str(payload))


def test_a_failed_install_leaves_no_version_directory(tmp_path, payload):
    """A half-copied version the launcher might pick up is worse than none."""
    (payload / install_layout.app_binary_name()).unlink()
    root = tmp_path / "ct"
    with pytest.raises(RuntimeError):
        appimage.install("0.6.0", override=str(root), source=str(payload))

    versions = root / install_layout.VERSIONS_DIRNAME
    assert not (versions / "0.6.0").exists()
    assert not (versions / "0.6.0.incoming").exists()


def test_reinstalling_the_same_version_replaces_it(tmp_path, payload):
    root = tmp_path / "ct"
    appimage.install("0.6.0", override=str(root), source=str(payload))
    stale = root / install_layout.VERSIONS_DIRNAME / "0.6.0" / "stale.txt"
    stale.write_text("left over from the previous install\n")

    appimage.install("0.6.0", override=str(root), source=str(payload))
    assert not stale.exists()


def test_already_installed_reports_accurately(tmp_path, payload):
    root = tmp_path / "ct"
    assert appimage.already_installed("0.6.0", override=str(root)) is False
    appimage.install("0.6.0", override=str(root), source=str(payload))
    assert appimage.already_installed("0.6.0", override=str(root)) is True
    assert appimage.already_installed("0.7.0", override=str(root)) is False


def test_desktop_entry_uses_absolute_paths(tmp_path, fake_home, payload):
    """The desktop environment reads this with neither our cwd nor our PATH."""
    home = fake_home

    root = tmp_path / "ct"
    launcher = appimage.install("0.6.0", override=str(root), source=str(payload))

    entry = home / ".local" / "share" / "applications" / appimage.DESKTOP_FILE_NAME
    assert entry.is_file()
    text = entry.read_text()
    assert f"Exec={launcher}" in text
    assert os.path.isabs(launcher)
    assert "Name=Combat Tracker" in text
    # Points at the launcher, never into versions/ -- that indirection is what
    # lets an update swap the version under a shortcut that keeps working.
    assert install_layout.VERSIONS_DIRNAME not in text.split("Exec=")[1].split("\n")[0]


def test_payload_dir_ignores_an_appdir_without_one(monkeypatch, tmp_path):
    monkeypatch.setenv(appimage.ENV_APPDIR, str(tmp_path))
    assert appimage.payload_dir() is None


def test_payload_dir_finds_usr_bin(monkeypatch, tmp_path, payload):
    monkeypatch.setenv(appimage.ENV_APPDIR, str(tmp_path / "appdir"))
    assert appimage.payload_dir() == str(payload)
