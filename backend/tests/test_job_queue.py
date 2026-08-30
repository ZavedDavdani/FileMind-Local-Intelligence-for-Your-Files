"""Job queue and worker pool test suite: State transitions, retry backoff, and failure isolation."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.queue import JobQueue
from app.engine.worker import WorkerPool


def test_job_queue_state_transitions():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_queue.db")
        db = DatabaseManager(db_path)
        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder("C:/test_folder")
            file_rec = repo.upsert_file(
                folder_id=folder["folder_id"],
                path="C:/test_folder/doc.txt",
                relative_path="doc.txt",
                filename="doc.txt",
                extension=".txt",
                size_bytes=100,
                modified_at="2026-08-30T00:00:00Z",
            )
            job = repo.enqueue_job(file_id=file_rec["file_id"], folder_id=folder["folder_id"])
            assert job["status"] == "PENDING"

        queue = JobQueue(db)
        # Claim job
        claimed = queue.claim_job()
        assert claimed is not None
        assert claimed["job_id"] == job["job_id"]
        assert claimed["status"] == "PROCESSING"

        # Complete job
        queue.complete_job(claimed["job_id"], claimed["file_id"], sha256="abc123hash")

        with db.session() as conn:
            repo = Repository(conn)
            updated_file = repo.get_file_by_id(file_rec["file_id"])
            assert updated_file["index_status"] == "INDEXED"
            assert updated_file["sha256"] == "abc123hash"


def test_job_retry_exponential_backoff():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_retry.db")
        db = DatabaseManager(db_path)
        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder("C:/test_folder")
            file_rec = repo.upsert_file(
                folder_id=folder["folder_id"],
                path="C:/test_folder/locked.docx",
                relative_path="locked.docx",
                filename="locked.docx",
                extension=".docx",
                size_bytes=200,
                modified_at="2026-08-30T00:00:00Z",
            )
            job = repo.enqueue_job(file_id=file_rec["file_id"], folder_id=folder["folder_id"])

        queue = JobQueue(db)
        # Attempt 1: Fail with retry
        claimed1 = queue.claim_job()
        queue.fail_job(claimed1["job_id"], claimed1["file_id"], "File locked by Word", attempts=1)

        with db.session() as conn:
            repo = Repository(conn)
            j1 = repo.list_jobs()[0]
            assert j1["status"] == "PENDING"
            assert j1["retry_at"] is not None
            assert j1["error"] == "File locked by Word"

        # Attempt 3: Exceed max attempts -> Permanent failure
        claimed2 = queue.claim_job()
        queue.fail_job(claimed1["job_id"], claimed1["file_id"], "Permanent access error", attempts=3)

        with db.session() as conn:
            repo = Repository(conn)
            j2 = repo.list_jobs()[0]
            assert j2["status"] == "FAILED"
            assert j2["retry_at"] is None


def test_worker_pool_processes_jobs_asynchronously():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_worker.db")
        db = DatabaseManager(db_path)
        with db.session() as conn:
            apply_migrations(conn)

        tmp_root = os.path.join(tmp_dir, "files")
        os.makedirs(tmp_root, exist_ok=True)
        file_path = os.path.join(tmp_root, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("Worker pool asynchronous execution test")

        with db.session() as conn:
            repo = Repository(conn)
            folder = repo.create_folder(tmp_root)
            file_rec = repo.upsert_file(
                folder_id=folder["folder_id"],
                path=file_path,
                relative_path="test.txt",
                filename="test.txt",
                extension=".txt",
                size_bytes=len("Worker pool asynchronous execution test"),
                modified_at="2026-08-30T00:00:00Z",
            )
            repo.enqueue_job(file_id=file_rec["file_id"], folder_id=folder["folder_id"])

        pool = WorkerPool(db, max_workers=2)
        pool.start()

        # Wait for worker to complete the job
        completed = False
        for _ in range(50):
            time.sleep(0.05)
            with db.session() as conn:
                repo = Repository(conn)
                f_state = repo.get_file_by_id(file_rec["file_id"])
                if f_state and f_state["index_status"] == "INDEXED":
                    completed = True
                    break

        pool.stop()
        assert completed is True
        assert f_state["sha256"] is not None
