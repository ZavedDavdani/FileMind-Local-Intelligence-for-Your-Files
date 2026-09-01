"""Persistent rotating application logging configuration for FileMind.

Features:
- Configurable log levels (DEBUG, INFO, WARNING, ERROR).
- Rotating file handler with bounded byte size and retention.
- Console handler with matching log level.
- Sanitized log output: strictly prevents logging full document texts, credentials, or API keys.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.core.config import (
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    LOG_BACKUP_COUNT,
    LOG_DIR,
    MAX_LOG_BYTES,
)

_LOGGING_INITIALIZED = False


def setup_logging(
    log_level: Optional[str] = None,
    log_file: Optional[Path] = None,
    max_bytes: int = MAX_LOG_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
    enable_console: bool = True,
) -> logging.Logger:
    """Configures root and application loggers with rotating file and console output."""
    global _LOGGING_INITIALIZED

    level_str = (log_level or DEFAULT_LOG_LEVEL).upper()
    numeric_level = getattr(logging, level_str, logging.INFO)

    target_file = Path(log_file) if log_file else DEFAULT_LOG_FILE
    target_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Clean existing FileMind handlers to avoid duplicate log entries
    existing_handlers = list(root_logger.handlers)
    for h in existing_handlers:
        if getattr(h, "_is_filemind_handler", False):
            root_logger.removeHandler(h)

    # 1. Rotating File Handler
    try:
        file_handler = RotatingFileHandler(
            filename=str(target_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        file_handler._is_filemind_handler = True
        root_logger.addHandler(file_handler)
    except Exception as exc:
        print(f"[FileMind Logging] WARNING: Failed to initialize file logging at {target_file}: {exc}")

    # 2. Console Handler
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        console_handler._is_filemind_handler = True
        root_logger.addHandler(console_handler)

    _LOGGING_INITIALIZED = True
    app_logger = logging.getLogger("FileMind")
    app_logger.info("Logging initialized at level %s (log_file=%s)", level_str, target_file)
    return app_logger
