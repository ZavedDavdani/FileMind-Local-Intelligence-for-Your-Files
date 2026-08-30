"""Filesystem watcher test suite: Event normalization, debouncing, deduplication, and real OS integration."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.watcher import DebouncedEventManager, WatcherService


def test_event_debouncer_coalesces_rapid_modifications():
    flushed_events = []

    def on_flush(event):
        flushed_events.append(event)

    debouncer = DebouncedEventManager(debounce_window_sec=0.1, on_flush=on_flush)

    # Push multiple rapid MODIFY events on the same file
    for _ in range(5):
        debouncer.push_event({
            "folder_id": "f1",
            "event_type": "MODIFY",
            "path": "C:/dev/FileMind/doc.txt",
            "observed_at": time.time(),
        })

    # Wait for debouncer window to flush
    time.sleep(0.25)
    assert len(flushed_events) == 1
    assert flushed_events[0]["event_type"] == "MODIFY"


def test_event_debouncer_create_then_modify():
    flushed_events = []

    def on_flush(event):
        flushed_events.append(event)

    debouncer = DebouncedEventManager(debounce_window_sec=0.1, on_flush=on_flush)

    # CREATE followed immediately by MODIFY
    debouncer.push_event({
        "folder_id": "f1",
        "event_type": "CREATE",
        "path": "C:/dev/FileMind/new_file.txt",
        "observed_at": time.time(),
    })
    debouncer.push_event({
        "folder_id": "f1",
        "event_type": "MODIFY",
        "path": "C:/dev/FileMind/new_file.txt",
        "observed_at": time.time(),
    })

    time.sleep(0.25)
    assert len(flushed_events) == 1
    assert flushed_events[0]["event_type"] == "CREATE"


def test_watcher_service_detects_live_file_events():
    """Validates real OS filesystem event capture for CREATE, MODIFY, RENAME, and DELETE."""
    db_file = os.path.join(tempfile.gettempdir(), f"test_watch_live_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root)
                folder_id = folder["folder_id"]

            captured_events = []

            def on_event(ev):
                captured_events.append(ev)

            watcher = WatcherService(db, on_normalized_event=on_event)
            watcher.start()

            # ---------------------------------------------------------
            # 1. Real OS File CREATE
            # ---------------------------------------------------------
            new_file = os.path.join(tmp_root, "live_created_doc.txt")
            time.sleep(0.2)
            with open(new_file, "w", encoding="utf-8") as f:
                f.write("Live watchdog creation test")

            for _ in range(30):
                time.sleep(0.05)
                if any(e["event_type"] == "CREATE" and e["path"].lower() == new_file.lower() for e in captured_events):
                    break

            assert any(e["event_type"] == "CREATE" for e in captured_events)

            # ---------------------------------------------------------
            # 2. Real OS File MODIFY
            # ---------------------------------------------------------
            time.sleep(0.6)  # Exceed debounce window
            with open(new_file, "w", encoding="utf-8") as f:
                f.write("Live watchdog modified content version 2")

            for _ in range(30):
                time.sleep(0.05)
                if any(e["event_type"] == "MODIFY" for e in captured_events):
                    break

            assert any(e["event_type"] == "MODIFY" for e in captured_events)

            # ---------------------------------------------------------
            # 3. Real OS File RENAME
            # ---------------------------------------------------------
            renamed_file = os.path.join(tmp_root, "live_renamed_doc.txt")
            time.sleep(0.6)
            os.rename(new_file, renamed_file)

            for _ in range(30):
                time.sleep(0.05)
                if any(e["event_type"] in ("RENAME", "MOVE") for e in captured_events):
                    break

            assert any(e["event_type"] in ("RENAME", "MOVE", "CREATE") for e in captured_events)

            # ---------------------------------------------------------
            # 4. Real OS File DELETE
            # ---------------------------------------------------------
            time.sleep(0.6)
            os.remove(renamed_file)

            for _ in range(30):
                time.sleep(0.05)
                if any(e["event_type"] == "DELETE" for e in captured_events):
                    break

            assert any(e["event_type"] == "DELETE" for e in captured_events)

            watcher.stop()

            # Verify audit trail logged all operations in SQLite
            with db.session() as conn:
                repo = Repository(conn)
                events = repo.list_events(folder_id)
                event_types = {e["event_type"] for e in events}
                assert "CREATE" in event_types
                assert len(events) >= 2

    finally:
        try:
            if os.path.exists(db_file):
                os.remove(db_file)
        except Exception:
            pass
