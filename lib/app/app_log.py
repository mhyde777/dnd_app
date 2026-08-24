# lib/app/app_log.py
"""
Application-wide logging.

In a packaged build there is no terminal, so anything printed to stdout is lost.
Everything routed through here lands in a rotating file under the config dir and
in an in-memory ring buffer that the in-app log viewer reads.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from collections import deque
from typing import Deque

from app.paths import config_path

_LOG_DIR = config_path("logs")
LOG_PATH = os.path.join(_LOG_DIR, "tracker.log")

_LOGGER_NAME = "dnd_tracker"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3
_RING_SIZE = 500

_configured = False


class _RingBufferHandler(logging.Handler):
    """Keeps the most recent records in memory for the in-app log viewer."""

    def __init__(self, capacity: int = _RING_SIZE) -> None:
        super().__init__()
        self.records: Deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(self.format(record))
        except Exception:
            # A logging handler must never raise into application code.
            pass


_ring = _RingBufferHandler()


def configure(level: int = logging.INFO) -> logging.Logger:
    """Set up file + ring-buffer + console handlers. Safe to call repeatedly."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception:
        # A read-only or missing home dir must not stop the app from starting.
        pass

    _ring.setLevel(level)
    _ring.setFormatter(fmt)
    logger.addHandler(_ring)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    _configured = True
    return logger


def get_logger() -> logging.Logger:
    if not _configured:
        return configure()
    return logging.getLogger(_LOGGER_NAME)


def recent(limit: int | None = None) -> list[str]:
    """Most recent formatted log lines, oldest first."""
    lines = list(_ring.records)
    if limit is not None:
        lines = lines[-limit:]
    return lines


def clear_ring() -> None:
    _ring.records.clear()
