# lib/ui/banner.py
"""
Persistent notification banners — the middle tier between a toast and a modal.

A toast auto-dismisses in a few seconds, so it's wrong for a condition that is
still true after you stop looking ("the bridge is down, your HP edits are not
reaching Foundry"). A modal is also wrong: it isn't fatal and it shouldn't stop
you mid-combat. A banner stays put until the condition clears or the user
dismisses it.

Banners are keyed. Re-showing the same key updates the existing banner in place
rather than stacking duplicates, so a repeated failure can't pile up.
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.app_log import get_logger

# background, border, text
_BANNER_STYLES = {
    "info":    ("#25324a", "#4a90d9", "#dce7f5"),
    "success": ("#1a4a2e", "#4ade80", "#e8f5ec"),
    "warning": ("#5c4420", "#e0a53f", "#f7ecd8"),
    "error":   ("#5c2020", "#f87171", "#f9e6e6"),
}

_LEVEL_ICONS = {
    "info": "ℹ",
    "success": "✓",
    "warning": "▲",
    "error": "✕",
}


class Banner(QFrame):
    """One dismissible strip. Optionally carries a single action button."""

    def __init__(
        self,
        key: str,
        message: str,
        level: str = "warning",
        action_label: Optional[str] = None,
        action: Optional[Callable[[], None]] = None,
        dismissable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._on_dismiss: Optional[Callable[[str], None]] = None

        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(10)

        self._icon = QLabel(self)
        self._icon.setFixedWidth(16)
        layout.addWidget(self._icon)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._label, stretch=1)

        self._action_button = QPushButton(self)
        self._action_button.setVisible(False)
        layout.addWidget(self._action_button)

        self._close_button = QPushButton("✕", self)
        self._close_button.setObjectName("bannerClose")
        self._close_button.setFixedSize(22, 22)
        self._close_button.setToolTip("Dismiss")
        self._close_button.setFlat(True)
        self._close_button.clicked.connect(self.dismiss)
        layout.addWidget(self._close_button)

        self.update_content(message, level, action_label, action, dismissable)

    def update_content(
        self,
        message: str,
        level: str = "warning",
        action_label: Optional[str] = None,
        action: Optional[Callable[[], None]] = None,
        dismissable: bool = True,
    ) -> None:
        bg, border, fg = _BANNER_STYLES.get(level, _BANNER_STYLES["warning"])
        self.setStyleSheet(
            f"QFrame {{ background-color: {bg};"
            f" border: 1px solid {border};"
            " border-radius: 5px; }"
            f" QLabel {{ color: {fg}; background: transparent; border: none;"
            "  font-weight: 600; }"
            f" QPushButton {{ color: {fg}; background: transparent;"
            f"  border: 1px solid {border}; border-radius: 3px; padding: 3px 10px; }}"
            f" QPushButton:hover {{ background-color: {border}; color: {bg}; }}"
            f" QPushButton#bannerClose {{ padding: 0; border: none;"
            "  font-size: 14px; font-weight: bold; }"
            f" QPushButton#bannerClose:hover {{ background-color: {border};"
            f"  color: {bg}; border-radius: 11px; }}"
        )
        self._icon.setText(_LEVEL_ICONS.get(level, "ℹ"))
        self._label.setText(message)

        # Disconnect any previous handler so an updated banner doesn't fire the
        # action from a stale call.
        try:
            self._action_button.clicked.disconnect()
        except TypeError:
            pass
        if action_label and action is not None:
            self._action_button.setText(action_label)
            self._action_button.clicked.connect(action)
            self._action_button.setVisible(True)
        else:
            self._action_button.setVisible(False)

        self._close_button.setVisible(dismissable)

    def set_dismiss_handler(self, handler: Callable[[str], None]) -> None:
        self._on_dismiss = handler

    def dismiss(self) -> None:
        if self._on_dismiss is not None:
            self._on_dismiss(self.key)


class BannerArea(QWidget):
    """
    Container that holds the active banners, top to bottom.

    Collapses to zero height when empty so it costs nothing in the normal case.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._banners: dict[str, Banner] = {}

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self.setVisible(False)

    def show_banner(
        self,
        key: str,
        message: str,
        level: str = "warning",
        action_label: Optional[str] = None,
        action: Optional[Callable[[], None]] = None,
        dismissable: bool = True,
    ) -> None:
        get_logger().log(
            {"error": 40, "warning": 30}.get(level, 20), "[Banner] %s", message
        )
        existing = self._banners.get(key)
        if existing is not None:
            existing.update_content(message, level, action_label, action, dismissable)
            return

        banner = Banner(key, message, level, action_label, action, dismissable, self)
        banner.set_dismiss_handler(self.clear_banner)
        self._banners[key] = banner
        self._layout.addWidget(banner)
        self.setVisible(True)

    def clear_banner(self, key: str) -> None:
        banner = self._banners.pop(key, None)
        if banner is None:
            return
        self._layout.removeWidget(banner)
        banner.deleteLater()
        self.setVisible(bool(self._banners))

    def clear_all(self) -> None:
        for key in list(self._banners):
            self.clear_banner(key)

    def active_keys(self) -> list[str]:
        return list(self._banners)
