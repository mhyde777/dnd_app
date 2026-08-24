"""
Help → Release Notes: the changelog, readable inside the app.

The point is informed consent about updates. A user who is told "0.2.0 is
available" and can immediately read what is in it can decide to take it or
ignore it; a bare version number gives them nothing to decide with. So the
same dialog serves both Help → Release Notes and the "What's New?" action on
the update banner.

CHANGELOG.md ships in the bundle, so this works offline and describes the
version actually running.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)

from app import srd_content
from app.version import __version__

_FILENAME = "CHANGELOG.md"


def changelog_path() -> Optional[Path]:
    """Locate CHANGELOG.md in the bundle or the source tree."""
    roots = []
    bundled = srd_content.content_dir()
    if bundled is not None:
        roots.append(bundled.parent)          # sits beside srd_content/
    roots.append(Path(__file__).resolve().parent.parent.parent)

    for root in roots:
        candidate = root / _FILENAME
        if candidate.is_file():
            return candidate
    return None


def read_changelog() -> str:
    path = changelog_path()
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def section_for(version: str, text: Optional[str] = None) -> str:
    """Just the entry for one version, for the "what's in this update" case.

    Falls back to the whole document rather than showing nothing -- a missing
    section should not leave the user with no information about an update.
    """
    text = read_changelog() if text is None else text
    if not text:
        return ""

    wanted = (version or "").strip().lstrip("vV")
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        # (?!#) matters: "### Added" also starts with ## and would end the
        # section after its first subheading.
        match = re.match(r"^##(?!#)\s*\[?([^\]\s]+)\]?", line)
        if not match:
            continue
        if start is not None:
            return "\n".join(lines[start:index]).strip()
        if match.group(1).lstrip("vV") == wanted:
            start = index
    if start is not None:
        return "\n".join(lines[start:]).strip()
    return text


class ReleaseNotesDialog(QDialog):
    def __init__(self, parent=None, version: Optional[str] = None) -> None:
        super().__init__(parent)
        only_one = version is not None
        self.setWindowTitle(
            f"What's New in {version}" if only_one else "Release Notes"
        )
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(680, 560)

        root = QVBoxLayout(self)

        header = QLabel(
            f"You are running {__version__}."
            if not only_one
            else f"You are running {__version__}. This is what {version} changes."
        )
        header.setWordWrap(True)
        root.addWidget(header)

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        text = section_for(version) if only_one else read_changelog()
        if text:
            body.setMarkdown(text)
        else:
            body.setPlainText(
                "No changelog shipped with this build.\n\n"
                "Release notes are at:\n"
                "https://github.com/mhyde777/dnd_app/releases"
            )
        root.addWidget(body, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
