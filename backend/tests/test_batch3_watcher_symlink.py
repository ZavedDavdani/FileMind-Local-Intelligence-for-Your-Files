"""Regression tests for Bug #12: Live Watcher Symlink / Junction Rejection."""

import os
import tempfile
import time
import pytest
from app.core.security import is_symlink_or_junction
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.watcher import DebouncedEventManager, FolderWatchHandler, WatcherService


def test_watcher_handler_ignores_symlinks():
    with tempfile.TemporaryDirectory() as tmp_root:
        real_file = os.path.join(tmp_root, "real.txt")
        with open(real_file, "w", encoding="utf-8") as f:
            f.write("Real file content")

        debouncer = DebouncedEventManager(debounce_window_sec=0.05, on_flush_batch=lambda b: None)
        handler = FolderWatchHandler(
            folder_id="test-folder",
            folder_path=tmp_root,
            exclude_patterns=[],
            debouncer=debouncer,
        )

        # Real file should NOT be ignored
        assert not handler._should_ignore(real_file, is_dir=False)

        # Create a symlink (if supported on OS/privilege)
        link_file = os.path.join(tmp_root, "link.txt")
        try:
            os.symlink(real_file, link_file)
            assert is_symlink_or_junction(link_file)
            # Watcher should reject the symlink
            assert handler._should_ignore(link_file, is_dir=False)
        except (OSError, NotImplementedError):
            # Windows without Developer Mode / SeCreateSymbolicLinkPrivilege
            pytest.skip("Symlink creation not permitted in current OS environment")


def test_watcher_batch_processor_drops_symlinks():
    db_file = os.path.join(tempfile.gettempdir(), f"test_watch_sym_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            real_file = os.path.join(tmp_root, "real.txt")
            with open(real_file, "w", encoding="utf-8") as f:
                f.write("Real file content")

            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root, integrity_mode="NORMAL")
                folder_id = folder["folder_id"]

            watcher_service = WatcherService(db)

            # Test standard file CREATE
            events = [
                {
                    "folder_id": folder_id,
                    "event_type": "CREATE",
                    "path": real_file,
                    "is_directory": False,
                }
            ]
            watcher_service._handle_flushed_batch(events)

            with db.session() as conn:
                repo = Repository(conn)
                rec = repo.get_file_by_path(real_file)
                assert rec is not None
                assert rec["index_status"] in ("DISCOVERED", "QUEUED")

            # Create symlink and try to process CREATE event for it
            link_file = os.path.join(tmp_root, "symlink_doc.txt")
            try:
                os.symlink(real_file, link_file)
            except (OSError, NotImplementedError):
                return  # Skip symlink event test if OS does not allow symlink creation

            symlink_events = [
                {
                    "folder_id": folder_id,
                    "event_type": "CREATE",
                    "path": link_file,
                    "is_directory": False,
                }
            ]
            watcher_service._handle_flushed_batch(symlink_events)

            with db.session() as conn:
                repo = Repository(conn)
                sym_rec = repo.get_file_by_path(link_file)
                # Symlink should NOT have been inserted into files table
                assert sym_rec is None
    finally:
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
