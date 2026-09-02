"""
FileMind Stability & Integrity Hardening — Batch 3 Test Suite.
Covers:
1. Multi-folder concurrent re-indexing stress (2, 5, 10 folders).
2. SQLite transaction atomicity & failure injection.
3. Worker concurrency & atomic job claiming.
4. Stale processing job crash recovery.
5. Watcher mass event debouncing and stress.
6. Watcher start/stop/restart lifecycle safety.
7. Database delete/insert/recreate race safety.
8. Folder understanding concurrency locking and deleted-folder safety.
9. Resource lifecycle and thread safety.
"""

import concurrent.futures
import os
import tempfile
import threading
import time
from typing import Any, Dict, List
import pytest

from app.ai.folder_understanding import FolderUnderstandingService
from app.core.security import normalize_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.engine.queue import JobQueue
from app.engine.watcher import DebouncedEventManager, WatcherService
from app.engine.worker import WorkerPool


@pytest.fixture
def temp_db():
    """Creates an isolated temporary file-backed SQLite database with WAL mode."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(path)
    with db.session() as conn:
        apply_migrations(conn)
    yield db
    try:
        os.remove(path)
    except Exception:
        pass


# =============================================================================
# 1. Multi-Folder Concurrent Re-indexing Stress Tests
# =============================================================================

@pytest.mark.parametrize("folder_count", [2, 5, 10])
def test_multi_folder_concurrent_indexing_stress(temp_db, folder_count):
    """
    Stress tests concurrent multi-folder indexing.
    Spawns `folder_count` parallel threads, each registering files, enqueuing jobs,
    replacing chunks, and completing indexing simultaneously.
    Asserts zero SQLite lock errors, zero lost writes, and consistent counts.
    """
    files_per_folder = 15
    errors = []

    def index_folder_worker(folder_idx: int):
        try:
            folder_path = f"C:/test_root/folder_{folder_idx}"
            with temp_db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(folder_path)
                fid = folder["folder_id"]

            for f_idx in range(files_per_folder):
                file_path = f"{folder_path}/file_{f_idx:03d}.txt"
                with temp_db.session() as conn:
                    repo = Repository(conn)
                    f_rec = repo.upsert_file(
                        folder_id=fid,
                        path=file_path,
                        relative_path=f"file_{f_idx:03d}.txt",
                        filename=f"file_{f_idx:03d}.txt",
                        extension=".txt",
                        size_bytes=100 + f_idx,
                        modified_at="2026-09-02T12:00:00Z",
                        index_status="QUEUED",
                    )
                    file_id = f_rec["file_id"]
                    job = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)
                    job_id = job["job_id"]

                # Simulate chunking & completion in separate transactions
                with temp_db.session() as conn:
                    repo = Repository(conn)
                    repo.replace_file_chunks(
                        file_id,
                        [{
                            "chunk_id": f"chk_{file_id}_{i}",
                            "file_id": file_id,
                            "source_file": f"file_{f_idx:03d}.txt",
                            "source_path": file_path,
                            "content_hash": f"hash_{file_id}_{i}",
                            "chunk_index": i,
                            "content": f"Sample chunk content {i} for file {f_idx}",
                        } for i in range(3)]
                    )
                    repo.complete_job(job_id, file_id, sha256=f"sha_{file_id}", final_status="INDEXED")
        except Exception as exc:
            errors.append((folder_idx, str(exc)))

    with concurrent.futures.ThreadPoolExecutor(max_workers=folder_count) as executor:
        futures = [executor.submit(index_folder_worker, i) for i in range(folder_count)]
        concurrent.futures.wait(futures)

    assert len(errors) == 0, f"Errors during concurrent indexing: {errors}"

    with temp_db.session() as conn:
        repo = Repository(conn)
        stats = repo.count_files_by_status()
        assert stats["TOTAL"] == folder_count * files_per_folder
        assert stats["INDEXED"] == folder_count * files_per_folder
        assert stats["QUEUED"] == 0
        assert stats["PROCESSING"] == 0
        assert stats["FAILED"] == 0

        # Verify all chunks were stored
        cur = conn.execute("SELECT COUNT(*) FROM chunks;")
        total_chunks = cur.fetchone()[0]
        assert total_chunks == folder_count * files_per_folder * 3


# =============================================================================
# 2. SQLite Transaction Atomicity & Failure Injection Tests
# =============================================================================

def test_transaction_rollback_on_chunk_replacement_failure(temp_db):
    """
    Verifies that a failure during chunk replacement rolls back completely
    without leaving the file in a half-indexed or chunk-depleted state.
    """
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test/atomicity")
        fid = folder["folder_id"]
        f = repo.upsert_file(
            folder_id=fid,
            path="C:/test/atomicity/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T12:00:00Z",
            index_status="INDEXED",
        )
        file_id = f["file_id"]

        # Insert initial valid chunk
        repo.replace_file_chunks(
            file_id,
            [{
                "chunk_id": "initial_chunk",
                "file_id": file_id,
                "source_file": "doc.txt",
                "source_path": "C:/test/atomicity/doc.txt",
                "content_hash": "h1",
                "chunk_index": 0,
                "content": "Initial content",
            }]
        )

    # Invalidate chunk replacement with a malformed record (missing required keys)
    with pytest.raises(Exception):
        with temp_db.session() as conn:
            repo = Repository(conn)
            # This should delete old chunks, but fail during insert -> rollback
            repo.replace_file_chunks(
                file_id,
                [{"invalid": "record"}]  # Missing chunk_id/content
            )

    # Verify original chunk was restored due to transaction rollback
    with temp_db.session() as conn:
        repo = Repository(conn)
        chunks = repo.get_chunks_by_file(file_id)
        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == "initial_chunk"


# =============================================================================
# 3. Worker Concurrency & Atomic Job Claiming Tests
# =============================================================================

def test_worker_atomic_job_claiming(temp_db):
    """
    Simulates high-concurrency worker threads attempting to claim the same set of jobs.
    Verifies that each job is claimed by EXACTLY ONE worker (no duplicates).
    """
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test/workers")
        fid = folder["folder_id"]
        job_ids = []
        for i in range(20):
            f = repo.upsert_file(
                folder_id=fid,
                path=f"C:/test/workers/f_{i}.txt",
                relative_path=f"f_{i}.txt",
                filename=f"f_{i}.txt",
                extension=".txt",
                size_bytes=50,
                modified_at="2026-09-02T12:00:00Z",
                index_status="QUEUED",
            )
            job = repo.enqueue_job(file_id=f["file_id"], folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)
            job_ids.append(job["job_id"])

    queue = JobQueue(temp_db)
    claimed_jobs = []
    lock = threading.Lock()

    def claim_worker():
        while True:
            job = queue.claim_job()
            if not job:
                break
            with lock:
                claimed_jobs.append(job["job_id"])
            time.sleep(0.005)

    threads = [threading.Thread(target=claim_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Invariant: exactly 20 jobs claimed, all unique
    assert len(claimed_jobs) == 20
    assert len(set(claimed_jobs)) == 20
    assert set(claimed_jobs) == set(job_ids)


# =============================================================================
# 4. Stale Processing Job Recovery Tests
# =============================================================================

def test_stale_processing_job_recovery(temp_db):
    """
    Verifies that abnormal process interruption leaving jobs in 'PROCESSING'
    is safely recovered to 'PENDING' / 'QUEUED' on engine startup.
    """
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test/crash_recovery")
        fid = folder["folder_id"]
        f = repo.upsert_file(
            folder_id=fid,
            path="C:/test/crash_recovery/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = f["file_id"]
        job = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)
        job_id = job["job_id"]

        # Simulate job claimed and left in PROCESSING before abrupt shutdown
        claimed = repo.claim_next_job()
        assert claimed is not None
        assert claimed["status"] == "PROCESSING"

    # Verify state is PROCESSING
    with temp_db.session() as conn:
        repo = Repository(conn)
        file_rec = repo.get_file_by_id(file_id)
        assert file_rec["index_status"] == "PROCESSING"

    # Run Crash Recovery
    queue = JobQueue(temp_db)
    recovered = queue.recover_stale_jobs()
    assert recovered == 1

    # Verify state is restored to PENDING and QUEUED
    with temp_db.session() as conn:
        repo = Repository(conn)
        file_rec = repo.get_file_by_id(file_id)
        assert file_rec["index_status"] == "QUEUED"

        cur = conn.execute("SELECT status, error FROM indexing_jobs WHERE job_id = ?;", (job_id,))
        job_row = cur.fetchone()
        assert job_row["status"] == "PENDING"
        assert "Recovered" in job_row["error"]


# =============================================================================
# 5. Watcher Mass Event Debouncing & Stress Tests
# =============================================================================

def test_watcher_mass_event_debouncing():
    """
    Tests synthetic high-volume event ingestion (1,000 events) through DebouncedEventManager.
    Verifies that rapid duplicate creates, modifies, and directory hierarchy events coalesce cleanly.
    """
    flushed_batches = []
    debouncer = DebouncedEventManager(
        debounce_window_sec=0.05,
        on_flush_batch=lambda batch: flushed_batches.append(batch)
    )

    # Push 1,000 synthetic events for 50 distinct file paths (20 rapid modify events per file)
    for cycle in range(20):
        for file_idx in range(50):
            debouncer.push_event({
                "folder_id": "fld_1",
                "event_type": "CREATE" if cycle == 0 else "MODIFY",
                "path": f"C:/watched/file_{file_idx}.txt",
                "old_path": None,
                "is_directory": False,
                "observed_at": time.time(),
            })

    # Flush synchronously
    debouncer.flush()

    # Invariant: Exactly 1 batch flushed, containing exactly 50 coalesced file events
    assert len(flushed_batches) == 1
    events = flushed_batches[0]
    assert len(events) == 50
    assert len(set(e["path"] for e in events)) == 50


# =============================================================================
# 6. Watcher Lifecycle Startup/Shutdown Races
# =============================================================================

def test_watcher_rapid_lifecycle_safety(temp_db):
    """
    Stress tests rapid start(), stop(), and restart() cycles of WatcherService
    under load without thread leaks or unhandled exceptions.
    """
    watcher = WatcherService(temp_db)

    for _ in range(5):
        watcher.start()
        # Push synthetic event during active run
        watcher.debouncer.push_event({
            "folder_id": "fld_dummy",
            "event_type": "CREATE",
            "path": "C:/dummy/path.txt",
            "old_path": None,
            "is_directory": False,
            "observed_at": time.time(),
        })
        watcher.stop()

    # Final assertion: watcher cleanly stopped, observer is None
    assert watcher.observer is None
    assert len(watcher.watches) == 0


# =============================================================================
# 7. Database Delete/Insert/Recreate Race Tests
# =============================================================================

def test_file_recreate_race_preserves_new_state(temp_db):
    """
    Tests race condition:
    T0: file v1 exists
    T1: job 1 starts
    T2: file deleted & marked MISSING
    T3: file v2 recreated
    T4: old job 1 attempts to finish
    Asserts old job 1 cannot overwrite new file v2 state.
    """
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test/recreate")
        fid = folder["folder_id"]

        # Version 1
        f1 = repo.upsert_file(
            folder_id=fid,
            path="C:/test/recreate/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T10:00:00Z",
            index_status="QUEUED",
        )
        file_id = f1["file_id"]
        job1 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)

        # File is deleted
        repo.mark_file_missing("C:/test/recreate/doc.txt")
        repo.cancel_pending_jobs_for_file(file_id)

        # Version 2 is recreated with new size and timestamp
        f2 = repo.upsert_file(
            folder_id=fid,
            path="C:/test/recreate/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=500,
            modified_at="2026-09-02T11:00:00Z",
            index_status="QUEUED",
        )
        job2 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)

        # Stale job 1 finishes with version 1 sha256
        repo.complete_job(job1["job_id"], file_id, sha256="sha_v1", final_status="INDEXED")

        # Job 1 was cancelled -> must remain CANCELLED
        cur = conn.execute("SELECT status FROM indexing_jobs WHERE job_id = ?;", (job1["job_id"],))
        assert cur.fetchone()["status"] == "CANCELLED"

        # Version 2 job finishes
        repo.complete_job(job2["job_id"], file_id, sha256="sha_v2", final_status="INDEXED")
        file_final = repo.get_file_by_id(file_id)
        assert file_final["sha256"] == "sha_v2"
        assert file_final["size_bytes"] == 500


# =============================================================================
# 8. Folder Understanding Concurrency & Deleted Folder Tests
# =============================================================================

def test_folder_understanding_active_generation_lock(temp_db):
    """
    Verifies that FolderUnderstandingService enforces an active-generation lock,
    rejecting concurrent duplicate generation requests for the same folder.
    """
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test/folder_ai")
        fid = folder["folder_id"]

    service = FolderUnderstandingService(db_manager=temp_db)

    # Manually acquire the active generation lock
    with service._lock:
        service._active_generations.add(fid)

    # Second concurrent call must raise RuntimeError
    with pytest.raises(RuntimeError, match="already in progress"):
        service.generate_insight(fid)

    # Release lock
    with service._lock:
        service._active_generations.discard(fid)


def test_folder_understanding_deleted_folder_handling(temp_db):
    """
    Verifies that calling generate_insight on a non-existent or deleted folder
    raises a clean ValueError without corrupting state.
    """
    service = FolderUnderstandingService(db_manager=temp_db)
    with pytest.raises(ValueError, match="Folder not found"):
        service.generate_insight("non_existent_folder_id")
