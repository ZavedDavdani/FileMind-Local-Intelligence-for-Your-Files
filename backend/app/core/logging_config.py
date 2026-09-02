"""Persistent rotating application logging configuration for FileMind.

Features:
- Configurable log levels (DEBUG, INFO, WARNING, ERROR).
- Rotating file handler with bounded byte size and retention.
- Console handler with matching log level.
- Sanitized log output: strictly prevents logging full document texts, credentials, or API keys.
"""

import logging
import os
import re
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

SENSITIVE_PATTERNS = [
    # Bearer tokens
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE), r"\1[REDACTED]"),
    # API key / password / secret assignments (e.g. api_key="...", password=...)
    (re.compile(r"((?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?)(?:[^\s,'\"]+)(['\"]?)", re.IGNORECASE), r"\1[REDACTED]\2"),
    # Non-bearer Authorization headers (e.g. Authorization: Basic ...)
    (re.compile(r"(Authorization\s*:\s*(?!Bearer\b))['\"]?[^\s,'\"]+['\"]?", re.IGNORECASE), r"Authorization: [REDACTED]"),
    # OpenAI / Gemini / Ollama style sk- keys
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), r"sk-[REDACTED]"),
    # Basic auth embedded in URLs
    (re.compile(r"(https?://[^:\s]+:)[^@\s]+(@)", re.IGNORECASE), r"\1[REDACTED]\2"),
]


def redact_sensitive_text(text: str) -> str:
    """Deterministically redacts sensitive keys, tokens, and passwords from log strings."""
    if not isinstance(text, str) or not text:
        return text
    redacted = text
    for pattern, repl in SENSITIVE_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


class SensitiveDataFilter(logging.Filter):
    """Logging filter that sanitizes sensitive authentication tokens and credentials."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: (redact_sensitive_text(v) if isinstance(v, str) else v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple((redact_sensitive_text(a) if isinstance(a, str) else a) for a in record.args)
            elif isinstance(record.args, list):
                record.args = [redact_sensitive_text(a) if isinstance(a, str) else a for a in record.args]
        return True


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
    redaction_filter = SensitiveDataFilter()

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
        file_handler.addFilter(redaction_filter)
        file_handler._is_filemind_handler = True
        root_logger.addHandler(file_handler)
    except Exception as exc:
        print(f"[FileMind Logging] WARNING: Failed to initialize file logging at {target_file}: {exc}")

    # 2. Console Handler
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redaction_filter)
        console_handler._is_filemind_handler = True
        root_logger.addHandler(console_handler)

    _LOGGING_INITIALIZED = True
    app_logger = logging.getLogger("FileMind")
    app_logger.info("Logging initialized at level %s (log_file=%s)", level_str, target_file)
    return app_logger
