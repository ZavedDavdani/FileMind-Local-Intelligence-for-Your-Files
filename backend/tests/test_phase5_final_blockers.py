"""Focused regressions for the remaining Phase 5 lifecycle blockers."""

import threading
import pytest

from app.ai.generation_coordinator import LocalGenerationBusyError, LocalGenerationCoordinator
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.watcher import WatcherService


@pytest.fixture
def db(tmp_path):
    result = DatabaseManager(str(tmp_path / "phase5_blockers.db"))
    with result.session() as conn:
        apply_migrations(conn)
    return result


def test_generation_coordinator_is_single_slot_and_releases_after_error():
    coordinator = LocalGenerationCoordinator(1)
    with coordinator.acquire():
        with pytest.raises(LocalGenerationBusyError):
            with coordinator.acquire():
                pass
    with coordinator.acquire():
        pass
    with pytest.raises(RuntimeError):
        with coordinator.acquire():
            raise RuntimeError("provider failed")
    with coordinator.acquire():
        pass


def test_terminal_job_retention_preserves_active_and_keeps_newest_boundary(db):
    with db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/root")
        file_rec = repo.upsert_file(folder["folder_id"], "C:/root/a.txt", "a.txt", "a.txt", ".txt", 1, "2026-01-01", index_status="QUEUED")
        for i in range(1002):
            job = repo.enqueue_job(file_rec["file_id"], folder["folder_id"], job_type=f"TYPE_{i}", job_id=f"terminal-{i:04d}")
            conn.execute("UPDATE indexing_jobs SET status='COMPLETED', completed_at=? WHERE job_id=?", (f"2026-01-01T00:00:{i:04d}", job["job_id"]))
        pending = repo.enqueue_job(file_rec["file_id"], folder["folder_id"], job_type="ACTIVE", job_id="pending")
        assert repo.prune_terminal_jobs() == 2
        assert conn.execute("SELECT COUNT(*) FROM indexing_jobs WHERE status='COMPLETED'").fetchone()[0] == 1000
        assert conn.execute("SELECT status FROM indexing_jobs WHERE job_id=?", (pending["job_id"],)).fetchone()[0] == "PENDING"


def test_move_outside_root_marks_old_file_missing_and_never_indexes_destination(db, monkeypatch):
    with db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/root")
        file_rec = repo.upsert_file(folder["folder_id"], "C:/root/a.txt", "a.txt", "a.txt", ".txt", 1, "2026-01-01", index_status="INDEXED")
        job = repo.enqueue_job(file_rec["file_id"], folder["folder_id"], job_type="HASH_VERIFICATION")
    service = WatcherService(db)
    monkeypatch.setattr("os.path.exists", lambda _: True)
    service._process_event_sub_batch([{
        "folder_id": folder["folder_id"], "event_type": "MOVE", "path": "D:/external/a.txt",
        "old_path": "C:/root/a.txt", "is_directory": False,
    }])
    with db.session() as conn:
        repo = Repository(conn)
        assert repo.get_file_by_id(file_rec["file_id"])["index_status"] == "MISSING"
        assert conn.execute("SELECT status FROM indexing_jobs WHERE job_id=?", (job["job_id"],)).fetchone()[0] == "CANCELLED"
        assert repo.get_file_by_path("D:/external/a.txt") is None
