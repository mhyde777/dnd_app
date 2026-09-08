"""The published asset names have to be safe for the OLDEST updater in the field.

update_check.asset_for_platform() filters to the archives the updater can
unpack, which protects clients running this code. It does nothing for the
clients already installed: every build up to 0.5.1 selects an asset by platform
token alone, with no filter on the suffix, and *those* are the clients choosing
what to download when a new release appears.

0.6.0 was the first release to carry an .AppImage and a setup.exe. Both carried
their platform in the name, so every 0.5.1 client preferred them over the
archive beside them, downloaded 68MB and failed with "unsupported archive
type" -- self-update broken for everyone, by a release whose own updater was
correct. The names are the compatibility surface; this test pins them.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from app import update_check  # noqa: E402

# The token lists every released updater has used to match a platform. An
# artifact that is not meant to be auto-downloaded must contain none of them.
_LEGACY_TOKENS = {
    "linux": ("linux",),
    "win32": ("windows", "win64", "win"),
    "darwin": ("macos", "darwin", "osx"),
}


def _names(version: str = "9.9.9") -> dict:
    """The artifact names the build scripts produce, read from their source."""
    pkg = (ROOT / "package.sh").read_text()
    win = (ROOT / "package_WIN.sh").read_text()
    iss = (ROOT / "installer" / "windows" / "combat-tracker.iss").read_text()

    appimage = re.search(r'APPIMAGE_PATH="\$ROOT_DIR/dist/(\S+?)"', pkg).group(1)
    installer = re.search(r'INSTALLER_PATH="\$ROOT_DIR/dist/(\S+?)"', win).group(1)
    iss_name = re.search(r"^OutputBaseFilename=(\S+)$", iss, re.M).group(1)

    # STAGE_NAME is expanded too, and deliberately: naming the AppImage after
    # it is exactly the mistake this test exists to catch, and leaving the
    # variable unexpanded would let that mistake pass as "contains no token".
    stage_linux = f"combat-tracker-{version}-linux-x86_64"
    stage_win = f"combat-tracker-{version}-windows-x64"

    def expand(s: str, stage: str) -> str:
        out = (s.replace("${STAGE_NAME}", stage)
                .replace("${DIST_NAME}", "combat-tracker")
                .replace("${VERSION}", version)
                .replace("${ARCH}", "x86_64")
                .replace("{#AppVersion}", version))
        assert "$" not in out and "{#" not in out, (
            f"unexpanded variable in {out!r}; this test would silently pass"
        )
        return out

    return {
        "appimage": expand(appimage, stage_linux),
        "installer": expand(installer, stage_win),
        "iss": expand(iss_name, stage_win) + ".exe",
    }


def test_the_installer_name_matches_what_inno_setup_emits():
    """package_WIN.sh looks for the file the .iss wrote; a drift means no installer."""
    names = _names()
    assert names["installer"] == names["iss"]


@pytest.mark.parametrize("kind", ["appimage", "installer"])
def test_first_download_artifacts_carry_no_platform_token(kind):
    """Otherwise a pre-0.6.0 updater downloads one and cannot unpack it."""
    name = _names()[kind].lower()
    for platform, tokens in _LEGACY_TOKENS.items():
        for token in tokens:
            assert token not in name, (
                f"{name!r} contains {token!r}: a pre-0.6.0 client on {platform} "
                f"would select it over the archive and fail to extract it"
            )


def test_updatable_archives_still_carry_their_platform():
    """The flip side: the archive must be findable, by old clients and new."""
    for name, token in (("combat-tracker-9.9.9-linux-x86_64.tar.gz", "linux"),
                        ("combat-tracker-9.9.9-windows-x64.zip", "windows")):
        assert token in name
        assert name.endswith(update_check._UPDATABLE_SUFFIXES)


def test_current_updater_ignores_the_first_download_artifacts():
    names = _names("0.6.0")
    for kind in ("appimage", "installer"):
        assert not names[kind].lower().endswith(update_check._UPDATABLE_SUFFIXES)
