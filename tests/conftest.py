"""Keep the test suite out of the real ~/.dnd_tracker_config.

Nothing pointed the suite anywhere else, so every test that logged or touched
settings did it in the developer's own profile. The visible damage was the app
log: a run left dozens of "[Bridge] POST /commands failed" and "Local bridge
listening on 127.0.0.1:<random port>" lines in tracker.log, indistinguishable
from the real app's, and they nearly sent a diagnosis of a real sync problem
the wrong way.

Set at import time, not in a fixture: pytest imports conftest.py before it
collects any test module, and several test modules import the app -- and so
resolve the config directory -- at module level. Every test file shares one
throwaway profile for the run; tests that need a pristine one still make
their own (see the isolated_settings fixtures).
"""
import os
import shutil
import tempfile

from_env = os.environ.get("DND_TRACKER_CONFIG_DIR", "").strip()
if not from_env:
    _profile = tempfile.mkdtemp(prefix="dnd-tracker-test-profile-")
    os.environ["DND_TRACKER_CONFIG_DIR"] = _profile


def pytest_sessionfinish(session, exitstatus):
    if not from_env:
        # The log handler holds tracker.log open; rmtree copes on Linux and
        # macOS, and ignore_errors covers Windows, where it cannot.
        shutil.rmtree(_profile, ignore_errors=True)
