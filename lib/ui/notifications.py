# lib/ui/notifications.py
"""
User-facing error and status reporting.

Three levels, so failures stop being invisible:

  toast(...)        transient, non-blocking — "State saved", "Loaded PC group"
  InlineWarning     a strip inside a dialog — "Parse error: ..."
  report_warning()  something didn't work, but the app carried on
  report_error()    the action failed; shows the exception under "Show Details"

Everything reported here is also written to the log file via app.app_log.
"""
from __future__ import annotations

import traceback
from typing import Optional

from PyQt5.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer,
)
from PyQt5.QtWidgets import (
    QApplication, QGraphicsOpacityEffect, QLabel, QMessageBox, QWidget,
)

from app.app_log import get_logger

# Toast palette — kept local so notifications stay readable on any theme.
_TOAST_STYLES = {
    "info": ("#2a2a3c", "#c8a96e", "#e0dcc8"),
    "success": ("#1a4a2e", "#4ade80", "#e8f5ec"),
    "warning": ("#5c4420", "#e0a53f", "#f7ecd8"),
    "error": ("#5c2020", "#f87171", "#f9e6e6"),
}

_TOAST_MARGIN = 18
_TOAST_MAX_WIDTH = 380
_TOAST_SPACING = 8


# Inline warning strip. The import dialogs all grew their own copy of this
# label -- same colours, same ⚠ prefix, same hide-until-needed behaviour -- so
# it lives here with the rest of the reporting vocabulary.
WARNING_BG = "#FFF3CD"
WARNING_FG = "#856404"
WARNING_BORDER = "#FFEEBA"


class InlineWarning(QLabel):
    """A warning strip that sits in a dialog's layout, hidden until it has text.

    Unlike report_warning() this does not interrupt: it is for problems the
    user is expected to fix by editing what they pasted.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setStyleSheet(
            f"background:{WARNING_BG}; color:{WARNING_FG};"
            f"border:1px solid {WARNING_BORDER}; padding:6px; border-radius:3px;"
        )
        self.hide()

    def show_message(self, message: str) -> None:
        self.setText(f"\u26a0  {message}")
        self.show()


class _Toast(QWidget):
    """A single self-dismissing message pinned to the bottom-right of a window."""

    def __init__(self, parent: QWidget, message: str, level: str, duration_ms: int):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.SubWindow)

        bg, border, fg = _TOAST_STYLES.get(level, _TOAST_STYLES["info"])
        self._label = QLabel(message, self)
        self._label.setStyleSheet(
            f"background-color: {bg};"
            f" color: {fg};"
            f" border: 1px solid {border};"
            " border-radius: 6px;"
            " padding: 9px 14px;"
            " font-weight: 600;"
        )
        # Stay on one line up to a sensible width, then wrap — adjustSize() on a
        # word-wrapped label picks an arbitrarily narrow width otherwise.
        natural = self._label.sizeHint().width()
        if natural > _TOAST_MAX_WIDTH:
            self._label.setWordWrap(True)
            self._label.setFixedWidth(_TOAST_MAX_WIDTH)
            self._label.setFixedHeight(
                self._label.heightForWidth(_TOAST_MAX_WIDTH) or self._label.sizeHint().height()
            )
        else:
            self._label.setFixedSize(self._label.sizeHint())
        self.resize(self._label.size())

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self._fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_in.setDuration(140)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)

        self._fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_out.setDuration(260)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self._retire)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(1200, duration_ms))
        self._timer.timeout.connect(self._fade_out.start)

    def start(self) -> None:
        self.show()
        self.raise_()
        self._fade_in.start()
        self._timer.start()

    def _retire(self) -> None:
        manager = _manager_for(self.parentWidget(), create=False)
        if manager is not None:
            manager.remove(self)
        self.deleteLater()


class _ToastManager:
    """Stacks toasts upward from the bottom-right corner of one window."""

    def __init__(self, host: QWidget) -> None:
        self._host = host
        self._toasts: list[_Toast] = []

    def add(self, toast: _Toast) -> None:
        # Cap the stack so a burst of failures can't cover the whole window.
        while len(self._toasts) >= 4:
            oldest = self._toasts.pop(0)
            oldest.hide()
            oldest.deleteLater()
        self._toasts.append(toast)
        self.reposition()
        toast.start()

    def remove(self, toast: _Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self.reposition()

    def reposition(self) -> None:
        host = self._host
        if host is None:
            return
        y = host.height() - _TOAST_MARGIN
        # Sit above the status bar rather than covering the bridge indicator.
        status_bar = getattr(host, "statusBar", None)
        if callable(status_bar):
            try:
                bar = status_bar()
                if bar is not None and bar.isVisible():
                    y -= bar.height()
            except Exception:
                pass
        for toast in reversed(self._toasts):
            y -= toast.height()
            toast.move(QPoint(host.width() - toast.width() - _TOAST_MARGIN, y))
            y -= _TOAST_SPACING


def _manager_for(host: Optional[QWidget], create: bool = True) -> Optional[_ToastManager]:
    if host is None:
        return None
    manager = getattr(host, "_toast_manager", None)
    if manager is None and create:
        manager = _ToastManager(host)
        host._toast_manager = manager
    return manager


def _toast_host(parent: Optional[QWidget]) -> Optional[QWidget]:
    """Toasts belong to the main window, not to a transient dialog."""
    if parent is None:
        return QApplication.activeWindow()
    window = parent.window()
    return window if window is not None else parent


def reposition_toasts(host: QWidget) -> None:
    """Call from the host's resizeEvent to keep toasts corner-anchored."""
    manager = _manager_for(host, create=False)
    if manager is not None:
        manager.reposition()


def toast(
    parent: Optional[QWidget],
    message: str,
    level: str = "info",
    duration_ms: int = 3200,
) -> None:
    """Show a transient message. Never raises — reporting must not itself fail."""
    log = get_logger()
    log.log(
        {"error": 40, "warning": 30}.get(level, 20),
        message,
    )
    try:
        host = _toast_host(parent)
        if host is None:
            return
        manager = _manager_for(host)
        if manager is None:
            return
        manager.add(_Toast(host, message, level, duration_ms))
    except Exception:
        pass


def _detailed_box(
    parent: Optional[QWidget],
    icon,
    title: str,
    message: str,
    exc: Optional[BaseException],
) -> None:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(message)
    if exc is not None:
        box.setInformativeText(f"{type(exc).__name__}: {exc}")
        box.setDetailedText(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        )
    box.setStandardButtons(QMessageBox.Ok)
    box.exec_()


def report_error(
    parent: Optional[QWidget],
    title: str,
    message: str,
    exc: Optional[BaseException] = None,
) -> None:
    """The action failed and the user needs to know. Blocking, with details."""
    get_logger().error("%s — %s", title, message, exc_info=exc)
    try:
        _detailed_box(parent, QMessageBox.Critical, title, message, exc)
    except Exception:
        pass


def report_warning(
    parent: Optional[QWidget],
    title: str,
    message: str,
    exc: Optional[BaseException] = None,
) -> None:
    """Something went wrong but the app carried on."""
    get_logger().warning("%s — %s", title, message, exc_info=exc)
    try:
        _detailed_box(parent, QMessageBox.Warning, title, message, exc)
    except Exception:
        pass


def install_excepthook() -> None:
    """
    Route uncaught exceptions to the log and a dialog.

    Without this, an unhandled exception in a slot prints to a stdout nobody is
    watching and the app looks like it simply ignored the click.
    """
    import sys

    previous = sys.excepthook
    seen: set[str] = set()

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_tb)
            return
        get_logger().critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        # Identical repeat crashes (e.g. one per repaint) shouldn't spam dialogs.
        key = f"{exc_type.__name__}:{exc_value}"
        if key in seen:
            return
        seen.add(key)
        try:
            _detailed_box(
                QApplication.activeWindow(),
                QMessageBox.Critical,
                "Unexpected Error",
                "Something went wrong. The app is still running, but that "
                "action may not have completed.\n\n"
                "Details are in Help → Show Log.",
                exc_value,
            )
        except Exception:
            pass

    sys.excepthook = _hook
