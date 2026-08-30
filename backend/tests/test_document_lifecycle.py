"""Tests for document processing lifecycle: reprocessing, delete cleanup, and failure handling."""

import os
import tempfile
import time
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.worker import WorkerPool


@pytest.fixture
def test_db_and_pool():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_lifecycle.db")
        db_manager = DatabaseManager(db_path)
        with db_manager.session() as conn:
            apply_migrations(conn)

        pool = WorkerPool(db_manager, max_workers=2)
        pool.start()
        try:
            yield db_manager, pool, tmp_dir
        finally:
            pool.stop(timeout_sec=2.0)


def test_reprocessing_clears_stale_chunks(test_db_and_pool):
    """Verifies that modifying a file replaces stale active chunks without creating duplicates."""
    db_manager, pool, tmp_dir = test_db_and_pool
    file_path = os.path.join(tmp_dir, "doc_v1.md")
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# Version One\n\nInitial paragraph text.")

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(tmp_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=file_path,
            relative_path="doc_v1.md",
            filename="doc_v1.md",
            extension=".md",
            size_bytes=len("# Version One\n\nInitial paragraph text."),
            modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown",
        )
        file_id = file_rec["file_id"]
        repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")

    # Wait for initial processing
    time.sleep(1.0)

    with db_manager.session() as conn:
        repo = Repository(conn)
        v1_chunks = repo.get_chunks_by_file(file_id)
        assert len(v1_chunks) >= 1
        assert "Version One" in v1_chunks[0]["content"]

    # 2. Modify File Content (Version 2)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# Version Two\n\nUpdated completely new body text.\n\n## Subtopic\n\nSecond section.")

    with db_manager.session() as conn:
        repo = Repository(conn)
        # Queue new parse job
        repo.update_file_status(file_id, "QUEUED")
        repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")

    time.sleep(1.0)

    with db_manager.session() as conn:
        repo = Repository(conn)
        v2_chunks = repo.get_chunks_by_file(file_id)
        assert len(v2_chunks) >= 1
        # Assert old chunks are gone and only new chunks exist
        assert not any("Version One" in c["content"] for c in v2_chunks)
        assert any("Version Two" in c["content"] for c in v2_chunks)


def test_delete_cleanup_removes_chunks(test_db_and_pool):
    """Verifies that deleting a file removes all associated chunks."""
    db_manager, pool, tmp_dir = test_db_and_pool
    file_path = os.path.join(tmp_dir, "to_delete.md")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# Temporary Document\n\nThis will be deleted.")

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(tmp_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=file_path,
            relative_path="to_delete.md",
            filename="to_delete.md",
            extension=".md",
            size_bytes=len("# Temporary Document\n\nThis will be deleted."),
            modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown",
        )
        file_id = file_rec["file_id"]
        repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")

    time.sleep(1.0)

    with db_manager.session() as conn:
        repo = Repository(conn)
        assert len(repo.get_chunks_by_file(file_id)) >= 1

        # File is deleted
        os.remove(file_path)
        repo.update_file_status(file_id, "MISSING")
        repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"], job_type="DELETE_CLEANUP")

    time.sleep(1.0)

    with db_manager.session() as conn:
        repo = Repository(conn)
        chunks_after_delete = repo.get_chunks_by_file(file_id)
        assert len(chunks_after_delete) == 0


def test_failure_handling_malformed_document(test_db_and_pool):
    """Verifies that a malformed document fails gracefully with an inspectable reason without crashing the worker."""
    db_manager, pool, tmp_dir = test_db_and_pool
    corrupted_pdf = os.path.join(tmp_dir, "corrupted.pdf")

    # Write corrupt byte sequence
    with open(corrupted_pdf, "wb") as f:
        f.write(b"%PDF-1.4\nCorrupted binary rubbish that cannot be parsed\x00\xff\xee")

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(tmp_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=corrupted_pdf,
            relative_path="corrupted.pdf",
            filename="corrupted.pdf",
            extension=".pdf",
            size_bytes=60,
            modified_at="2026-01-01T00:00:00Z",
            mime_type="application/pdf",
        )
        file_id = file_rec["file_id"]
        repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")

    time.sleep(1.0)

    with db_manager.session() as conn:
        repo = Repository(conn)
        file_state = repo.get_file_by_id(file_id)
        # Should be marked FAILED with an explicit error
        assert file_state["index_status"] == "FAILED"
        assert file_state["indexing_error"] is not None
        assert pool.is_running
