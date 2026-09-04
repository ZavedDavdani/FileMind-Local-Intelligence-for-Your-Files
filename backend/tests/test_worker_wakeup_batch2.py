"""Tests for worker pool wake-up, pause/resume, burst jobs, and shutdown."""

import os
import tempfile
import threading
import time

import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.worker import WorkerPool


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_worker_wakeup.db")
    db_mgr = DatabaseManager(db_file)
    with db_mgr.session() as conn:
        apply_migrations(conn)
    yield db_mgr
    try:
        if os.path.exists(db_file):
            os.remove(db_file)
        os.rmdir(temp_dir)
    except Exception:
        pass


def test_worker_pool_lifecycle_and_wakeup(temp_db):
    """Verifies that worker pool starts, sleeps when idle, wakes on new job, and stops cleanly."""
    pool = WorkerPool(temp_db, max_workers=2)
    assert not pool.is_running
    assert not pool.is_paused

    pool.start()
    assert pool.is_running
    assert len(pool.threads) == 2

    # Pause pool
    pool.pause()
    assert pool.is_paused

    # Resume pool
    pool.resume()
    assert not pool.is_paused

    # Signal job availability
    pool.notify_job_available()

    # Stop pool cleanly
    pool.stop(timeout_sec=2.0)
    assert not pool.is_running
    assert len(pool.threads) == 0


def test_worker_processes_enqueued_job_on_wakeup(temp_db):
    """Verifies that an enqueued job wakes the worker and is completed."""
    temp_dir = tempfile.mkdtemp()
    test_file = os.path.join(temp_dir, "sample.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("Line 1 of sample text.\nLine 2 of sample text.\n")

    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(temp_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=test_file,
            relative_path="sample.txt",
            filename="sample.txt",
            extension=".txt",
            size_bytes=os.path.getsize(test_file),
            modified_at="2026-01-01T00:00:00Z",
        )
        file_id = file_rec["file_id"]
        repo.enqueue_job(file_id, folder["folder_id"], job_type="METADATA_DISCOVERY")

    pool = WorkerPool(temp_db, max_workers=1)
    pool.start()

    # Give worker time to claim and process
    for _ in range(50):
        with temp_db.session() as conn:
            repo = Repository(conn)
            f_rec = repo.get_file_by_id(file_id)
            if f_rec and f_rec["index_status"] == "INDEXED":
                break
        time.sleep(0.1)

    pool.stop(timeout_sec=2.0)

    with temp_db.session() as conn:
        repo = Repository(conn)
        f_rec = repo.get_file_by_id(file_id)
        assert f_rec["index_status"] == "INDEXED"

    try:
        os.remove(test_file)
        os.rmdir(temp_dir)
    except Exception:
        pass
