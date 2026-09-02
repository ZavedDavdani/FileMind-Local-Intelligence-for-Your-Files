"""Regression tests for Stability and Integrity Hardening Batch 2."""

import os
import pytest

from app.core.security import is_path_within_root
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.hierarchical import CHUNKER_VERSION


def test_mark_file_missing_cancels_jobs_and_prevents_resurrection():
    """Verifies that mark_file_missing cancels pending/processing jobs and prevents stale completion from resurrecting a missing file."""
    db = DatabaseManager(":memory:")
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/dev/test_folder")
        fid = folder["folder_id"]

        f = repo.upsert_file(
            folder_id=fid,
            path="C:/dev/test_folder/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = f["file_id"]

        # Enqueue job
        job = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)
        job_id = job["job_id"]

        # 1. File is marked missing while job is pending
        assert repo.mark_file_missing("C:/dev/test_folder/doc.txt") is True

        # File must be MISSING in DB
        file_rec = repo.get_file_by_id(file_id)
        assert file_rec["index_status"] == "MISSING"

        # Explicit cancel_pending_jobs_for_file cancels queued work
        cancelled_count = repo.cancel_pending_jobs_for_file(file_id)
        assert cancelled_count == 1

        cur = conn.execute("SELECT * FROM indexing_jobs WHERE job_id = ?;", (job_id,))
        job_rec = dict(cur.fetchone())
        assert job_rec["status"] == "CANCELLED"

        # 2. Stale in-flight worker execution calls complete_job for this job_id -> MUST NOT resurrect file or change job to COMPLETED
        repo.complete_job(job_id, file_id, sha256="fake_sha", final_status="INDEXED")

        # Invariants preserved:
        file_rec_after = repo.get_file_by_id(file_id)
        assert file_rec_after["index_status"] == "MISSING"  # NOT resurrected to INDEXED!

        cur = conn.execute("SELECT * FROM indexing_jobs WHERE job_id = ?;", (job_id,))
        job_rec_after = dict(cur.fetchone())
        assert job_rec_after["status"] == "CANCELLED"  # Stays CANCELLED, not COMPLETED!

        # 3. Test un-cancelled in-flight job also cannot resurrect a MISSING file
        job2 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)
        repo.complete_job(job2["job_id"], file_id, sha256="fake_sha2", final_status="INDEXED")
        file_rec_after2 = repo.get_file_by_id(file_id)
        assert file_rec_after2["index_status"] == "MISSING"


def test_complete_job_status_validation():
    """Verifies that complete_job validates final_status and rejects invalid statuses."""
    db = DatabaseManager(":memory:")
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/dev/test_folder_status")
        fid = folder["folder_id"]

        f = repo.upsert_file(
            folder_id=fid,
            path="C:/dev/test_folder_status/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = f["file_id"]
        job = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)

        # Invalid status must raise ValueError
        with pytest.raises(ValueError, match="Invalid file index_status"):
            repo.complete_job(job["job_id"], file_id, final_status="INVALID_STATUS_XYZ")

        # Valid lowercase status should be normalized to uppercase and succeed
        repo.complete_job(job["job_id"], file_id, final_status="skipped")
        file_rec = repo.get_file_by_id(file_id)
        assert file_rec["index_status"] == "SKIPPED"


def test_replace_file_chunks_authoritative_chunker_version():
    """Verifies that stored chunker_version defaults to the authoritative CHUNKER_VERSION constant."""
    db = DatabaseManager(":memory:")
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/dev/test_folder_chunker")
        fid = folder["folder_id"]

        f = repo.upsert_file(
            folder_id=fid,
            path="C:/dev/test_folder_chunker/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T12:00:00Z",
            index_status="INDEXED",
        )
        file_id = f["file_id"]

        # Insert chunk without explicit chunker_version in dict
        repo.replace_file_chunks(
            file_id,
            [{
                "chunk_id": "chk_version_test",
                "file_id": file_id,
                "source_file": "doc.txt",
                "source_path": "C:/dev/test_folder_chunker/doc.txt",
                "content_hash": "hash_123",
                "content": "Sample content",
            }]
        )

        vers = repo.get_file_chunk_versions(file_id)
        assert vers is not None
        assert vers["chunker_version"] == CHUNKER_VERSION


def test_watcher_root_containment_utility():
    """Verifies that is_path_within_root correctly accepts contained paths and rejects directory escapes/external paths."""
    root = "C:/dev/project_root"

    # Valid internal paths
    assert is_path_within_root("C:/dev/project_root/file.txt", root) is True
    assert is_path_within_root("C:/dev/project_root/sub/nested/file.txt", root) is True
    assert is_path_within_root("C:\\dev\\project_root\\sub\\file.txt", root) is True

    # Root equality
    assert is_path_within_root("C:/dev/project_root", root) is True

    # Traversal escape attempts
    assert is_path_within_root("C:/dev/project_root/../other/file.txt", root) is False
    assert is_path_within_root("C:/dev/other_root/file.txt", root) is False
    assert is_path_within_root("D:/project_root/file.txt", root) is False
    assert is_path_within_root("C:/dev/project_root_suffix/file.txt", root) is False
