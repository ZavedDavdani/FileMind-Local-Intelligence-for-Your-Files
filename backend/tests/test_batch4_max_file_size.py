"""Tests for Batch 4 Requirement 11: MAX_FILE_SIZE Ingestion Guard.

Verifies:
1. Files exceeding MAX_FILE_SIZE_BYTES are marked SKIPPED with an explicit indexing error.
2. No parse/chunk jobs are processed for oversized files.
3. Files within MAX_FILE_SIZE_BYTES are queued and indexed normally.
"""

import os
import pytest
from app.core import config
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    # Set limit to 1000 bytes for testing
    monkeypatch.setattr(config, "MAX_FILE_SIZE_BYTES", 1000)
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = db_dir / "test_max_size.db"
    db_manager = DatabaseManager(str(db_file))
    with db_manager.session() as conn:
        apply_migrations(conn)
    return db_manager, str(docs_dir)


def test_oversized_file_skipped_during_discovery(test_env):
    """Files exceeding MAX_FILE_SIZE_BYTES must be marked SKIPPED without queuing parse jobs."""
    db_manager, docs_dir = test_env

    # 1. Oversized file (2000 bytes > 1000 bytes limit)
    large_file = os.path.join(docs_dir, "large.txt")
    with open(large_file, "wb") as f:
        f.write(b"A" * 2000)

    # 2. Normal file (500 bytes <= 1000 bytes limit)
    small_file = os.path.join(docs_dir, "small.txt")
    with open(small_file, "wb") as f:
        f.write(b"B" * 500)

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(docs_dir)
        scanner = FilesystemScanner(repo)
        res = scanner.scan_folder(folder["folder_id"])

        # 2 files discovered
        assert res.new_files == 2
        # Only 1 job enqueued (for the small file)
        assert len(res.enqueued_job_ids) == 1

        # Check large file state
        large_rec = repo.get_file_by_path(large_file)
        assert large_rec["index_status"] == "SKIPPED"
        assert "exceeds limit" in large_rec["indexing_error"]

        # Check small file state
        small_rec = repo.get_file_by_path(small_file)
        assert small_rec["index_status"] == "QUEUED"
        assert small_rec["indexing_error"] is None
