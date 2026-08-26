"""The launcher: which version it starts, and what it does when one is broken.

Runs launcher.py as a subprocess against stand-in "builds" that are shell
scripts, so the version selection and rollback logic is exercised for real
without a 60MB PyInstaller build in the loop.
"""
import os
import subprocess
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(REPO, "launcher.py")


def make_version(root, version, works=True):
    """A stand-in build. A working one clears `launching`, as the real app does."""
    directory = root / "versions" / version
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "combat_tracker"
    if works:
        binary.write_text(
            f'#!/bin/sh\necho "RAN {version}"\n'
            f'rm -f "{root}/launching"\n'
        )
    else:
        # Starts, then dies without clearing the marker -- a build that cannot
        # get a window up.
        binary.write_text("#!/bin/sh\nexit 3\n")
    binary.chmod(0o755)
    return directory


def launch(root, *args):
    return subprocess.run(
        [sys.executable, LAUNCHER, *args],
        capture_output=True, text=True, cwd=str(root),
    )


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "install"
    (root / "versions").mkdir(parents=True)
    # launcher.py locates the root from its own path, so it has to live there.
    import shutil
    shutil.copy(LAUNCHER, root / "launcher.py")
    make_version(root, "0.2.0")
    make_version(root, "0.3.0")
    return root


def run(root, *args):
    return subprocess.run(
        [sys.executable, str(root / "launcher.py"), *args],
        capture_output=True, text=True,
    )


def test_starts_the_version_in_current(install):
    (install / "current").write_text("0.2.0\n")
    assert run(install).stdout.strip() == "RAN 0.2.0"


def test_follows_current_when_it_is_repointed(install):
    (install / "current").write_text("0.3.0\n")
    assert run(install).stdout.strip() == "RAN 0.3.0"


def test_falls_back_to_the_newest_when_current_names_nothing(install):
    (install / "current").write_text("9.9.9\n")
    assert run(install).stdout.strip() == "RAN 0.3.0"


def test_falls_back_to_the_newest_when_there_is_no_current(install):
    assert run(install).stdout.strip() == "RAN 0.3.0"


def test_a_version_that_cannot_start_is_rolled_back(install):
    make_version(install, "0.4.0", works=False)
    (install / "current").write_text("0.4.0\n")

    first = run(install)
    assert first.returncode == 3
    assert (install / "launching").exists(), (
        "a build that never cleared the marker is how the launcher knows it failed"
    )

    assert run(install).stdout.strip() == "RAN 0.3.0"
    assert (install / "current").read_text().strip() == "0.3.0", (
        "current must be repaired, or every later launch pays the same failed round trip"
    )
    assert run(install).stdout.strip() == "RAN 0.3.0"


def test_a_single_broken_version_is_still_attempted(install):
    import shutil
    shutil.rmtree(install / "versions" / "0.2.0")
    shutil.rmtree(install / "versions" / "0.3.0")
    make_version(install, "0.4.0", works=False)
    (install / "current").write_text("0.4.0\n")
    run(install)
    # Nothing to fall back to: better to keep trying than to refuse to start.
    assert run(install).returncode == 3


def test_wait_pid_waits_for_the_old_process(install):
    (install / "current").write_text("0.3.0\n")
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])
    started = time.time()
    result = run(install, "--wait-pid", str(sleeper.pid))
    assert time.time() - started > 1.2
    assert result.stdout.strip() == "RAN 0.3.0"


def test_wait_pid_does_not_stall_on_a_dead_pid(install):
    (install / "current").write_text("0.3.0\n")
    started = time.time()
    run(install, "--wait-pid", "999999")
    assert time.time() - started < 5.0


def test_reports_when_nothing_is_installed(install):
    import shutil
    shutil.rmtree(install / "versions")
    result = run(install)
    assert result.returncode == 1
    assert "no versions found" in (install / "launcher.log").read_text()
