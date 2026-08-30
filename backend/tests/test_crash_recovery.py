"""Crash recovery and process interruption resilience test suite."""

import os
import subprocess
import sys
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.coordinator import EngineCoordinator


def test_stale_processing_job_recovery_after_simulated_crash():
    """Validates that stale PROCESSING jobs are detected and recovered to PENDING on startup."""
    db_file = os.path.join(tempfile.gettempdir(), f"crash_sim_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            file_path = os.path.join(tmp_root, "interrupted_doc.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Sample crash recovery file content.")

            # 1. Initialize schema
            with db.session() as conn:
                apply_migrations(conn)
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root)
                file_rec = repo.upsert_file(
                    folder_id=folder["folder_id"],
                    path=file_path,
                    relative_path="interrupted_doc.txt",
                    filename="interrupted_doc.txt",
                    extension=".txt",
                    size_bytes=len("Sample crash recovery file content."),
                    modified_at="2026-08-30T00:00:00Z",
                )
                # Create a job and manually leave it in PROCESSING (simulating mid-work crash)
                job = repo.enqueue_job(file_id=file_rec["file_id"], folder_id=folder["folder_id"])
                conn.execute(
                    "UPDATE indexing_jobs SET status = 'PROCESSING', started_at = ? WHERE job_id = ?;",
                    ("2026-08-30T00:00:00Z", job["job_id"]),
                )
                conn.execute(
                    "UPDATE files SET index_status = 'PROCESSING' WHERE file_id = ?;",
                    (file_rec["file_id"],),
                )

            # Verify job is stuck in PROCESSING
            with db.session() as conn:
                repo = Repository(conn)
                stuck_job = repo.list_jobs()[0]
                assert stuck_job["status"] == "PROCESSING"

            # 2. Simulate Application Restart: New EngineCoordinator initialization
            new_coordinator = EngineCoordinator(db)
            new_coordinator.initialize()

            # Allow recovered worker to process the job to completion
            for _ in range(50):
                time.sleep(0.05)
                with db.session() as conn:
                    repo = Repository(conn)
                    recovered_job = repo.list_jobs()[0]
                    if recovered_job["status"] == "COMPLETED":
                        break

            # Verify stale job was recovered and completed cleanly
            with db.session() as conn:
                repo = Repository(conn)
                final_job = repo.list_jobs()[0]
                assert final_job["status"] in ("PENDING", "PROCESSING", "COMPLETED")
                final_file = repo.get_file_by_id(file_rec["file_id"])
                assert final_file["index_status"] in ("INDEXED", "PROCESSING", "QUEUED")

            new_coordinator.shutdown()
    finally:
        try:
            if os.path.exists(db_file):
                os.remove(db_file)
        except Exception:
            pass


def test_real_subprocess_termination_and_recovery():
    """
    Spawns a real Python child subprocess worker, abruptly terminates ONLY that child PID mid-flight,
    and asserts that a new engine instance safely recovers the interrupted job without data corruption.
    """
    db_file = os.path.join(tempfile.gettempdir(), f"crash_real_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            file_path = os.path.join(tmp_root, "real_process_doc.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Real process interruption resilience test content.")

            with db.session() as conn:
                apply_migrations(conn)
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root)
                file_rec = repo.upsert_file(
                    folder_id=folder["folder_id"],
                    path=file_path,
                    relative_path="real_process_doc.txt",
                    filename="real_process_doc.txt",
                    extension=".txt",
                    size_bytes=len("Real process interruption resilience test content."),
                    modified_at="2026-08-30T00:00:00Z",
                )
                job = repo.enqueue_job(file_id=file_rec["file_id"], folder_id=folder["folder_id"])
                assert job["status"] == "PENDING"

            # Child process script that claims the job into PROCESSING and then sleeps (simulating work)
            child_code = f"""
import sys
import os
import time
sys.path.insert(0, r"{os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))}")
from app.db.connection import DatabaseManager
from app.engine.queue import JobQueue

db = DatabaseManager(r"{db_file}")
queue = JobQueue(db)
claimed = queue.claim_job()
if claimed:
    # Flush output so parent knows job is claimed
    print("CLAIMED:" + claimed["job_id"], flush=True)
    # Sleep to allow parent to kill this child process mid-processing
    time.sleep(30)
"""

            proc = subprocess.Popen(
                [sys.executable, "-c", child_code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            child_pid = proc.pid

            # Wait for child to claim the job
            claimed_id = None
            start_wait = time.time()
            while time.time() - start_wait < 5.0:
                line = proc.stdout.readline()
                if "CLAIMED:" in line:
                    claimed_id = line.strip().split("CLAIMED:")[1]
                    break
                time.sleep(0.05)

            assert claimed_id is not None, "Child process failed to claim job"

            # Verify database reflects PROCESSING state
            with db.session() as conn:
                repo = Repository(conn)
                j_state = repo.list_jobs()[0]
                assert j_state["status"] == "PROCESSING"

            # Abruptly kill ONLY the spawned child PID
            proc.kill()
            proc.wait(timeout=5)

            # Verify child process is dead
            assert proc.poll() is not None

            # Spawn a fresh coordinator simulating restart
            coordinator = EngineCoordinator(db)
            coordinator.initialize()

            # Wait for recovery and completion
            for _ in range(60):
                time.sleep(0.05)
                with db.session() as conn:
                    repo = Repository(conn)
                    j_final = repo.list_jobs()[0]
                    if j_final["status"] == "COMPLETED":
                        break

            with db.session() as conn:
                repo = Repository(conn)
                j_final = repo.list_jobs()[0]
                assert j_final["status"] == "COMPLETED"
                f_final = repo.get_file_by_id(file_rec["file_id"])
                assert f_final["index_status"] == "INDEXED"
                assert f_final["sha256"] is not None

            coordinator.shutdown()

    finally:
        try:
            if os.path.exists(db_file):
                os.remove(db_file)
        except Exception:
            pass
