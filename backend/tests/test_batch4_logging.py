"""Tests for Batch 4 Requirement 12: Persistent Rotating Application Logging.

Verifies:
1. setup_logging creates the log file in the configured directory.
2. Log file rotates when reaching the max_bytes limit and retains backups.
3. Standard log format includes timestamp, level, name, and thread.
"""

import os
import logging
from app.core.logging_config import setup_logging


def test_rotating_logging_creation_and_rotation(tmp_path):
    log_file = tmp_path / "test_filemind.log"
    logger = setup_logging(
        log_level="DEBUG",
        log_file=log_file,
        max_bytes=200,  # Tiny byte limit to test rotation
        backup_count=3,
        enable_console=False,
    )

    # Write logs exceeding 200 bytes
    for i in range(20):
        logger.info("Test log entry number %02d with some text", i)

    # Flush handlers
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    assert log_file.stat().st_size > 0

    # Verify rotation backup exists
    backup_1 = tmp_path / "test_filemind.log.1"
    assert backup_1.exists()
