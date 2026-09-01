"""Regression tests for Bug #15: Debounced Event Flush Batching & Backpressure."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.watcher import WatcherService


def test_large_event_batch_split_into_bounded_sub_batches():
    db_file = os.path.join(tempfile.gettempdir(), f"test_batch_flush_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root, integrity_mode="NORMAL")
                folder_id = folder["folder_id"]

            watcher_service = WatcherService(db)

            # Create 550 events (more than WATCHER_BATCH_SIZE=200)
            events = []
            for i in range(550):
                file_path = os.path.join(tmp_root, f"file_{i}.txt")
                # Create the file on disk so CREATE event is valid
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"content {i}")
                events.append({
                    "folder_id": folder_id,
                    "event_type": "CREATE",
                    "path": file_path,
                    "is_directory": False,
                })

            # Process the large batch
            watcher_service._handle_flushed_batch(events)

            # Verify all 550 files were inserted and all events logged
            with db.session() as conn:
                repo = Repository(conn)
                files = repo.list_files(folder_id=folder_id, limit=1000)
                assert len(files) == 550

                # Check audit log count
                cur = conn.execute("SELECT COUNT(*) FROM file_events WHERE folder_id = ?;", (folder_id,))
                count = cur.fetchone()[0]
                assert count == 550
    finally:
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
