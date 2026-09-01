"""Regression tests for Bug #13: JobQueue permanent failure semantics."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.queue import JobQueue


def test_job_queue_permanent_failure_bypasses_retry():
    db_file = os.path.join(tempfile.gettempdir(), f"test_perm_fail_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with db.session() as conn:
            repo = Repository(conn)
            f_norm = repo.create_folder(r"C:\test_folder", integrity_mode="NORMAL")
            fid = f_norm["folder_id"]
            file_rec = repo.upsert_file(
                folder_id=fid,
                path=r"C:\test_folder\corrupted.pdf",
                relative_path="corrupted.pdf",
                filename="corrupted.pdf",
                extension=".pdf",
                size_bytes=100,
                modified_at="2026-01-01T00:00:00Z",
            )
            file_id = file_rec["file_id"]
            job = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE")
            job_id = job["job_id"]

        queue = JobQueue(db)

        # 1. Permanent failure on attempt 1 (e.g. unrecoverable parse corruption)
        success = queue.fail_job(
            job_id=job_id,
            file_id=file_id,
            error_message="Corrupted PDF trailer",
            attempts=1,
            permanent=True,
        )
        assert success is True

        with db.session() as conn:
            repo = Repository(conn)
            # Job should immediately be FAILED with NO retry_at
            jobs = repo.list_jobs(status="FAILED")
            assert len(jobs) == 1
            assert jobs[0]["job_id"] == job_id
            assert jobs[0]["status"] == "FAILED"
            assert jobs[0]["retry_at"] is None
            assert jobs[0]["error"] == "Corrupted PDF trailer"

            # File should be marked FAILED
            f = repo.get_file_by_id(file_id)
            assert f["index_status"] == "FAILED"
            assert f["indexing_error"] == "Corrupted PDF trailer"

        # 2. Non-permanent failure on attempt 1 should set retry_at (exponential backoff)
        with db.session() as conn:
            repo = Repository(conn)
            job2 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="HASH_VERIFICATION")
            job2_id = job2["job_id"]

        queue.fail_job(
            job_id=job2_id,
            file_id=file_id,
            error_message="Transient I/O lock",
            attempts=1,
            permanent=False,
        )

        with db.session() as conn:
            repo = Repository(conn)
            jobs2 = repo.list_jobs(status="PENDING")
            pending_retry = [j for j in jobs2 if j["job_id"] == job2_id]
            assert len(pending_retry) == 1
            assert pending_retry[0]["retry_at"] is not None
            assert pending_retry[0]["error"] == "Transient I/O lock"
    finally:
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
