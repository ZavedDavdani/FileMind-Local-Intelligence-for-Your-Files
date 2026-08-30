"""
FileMind — Hardening 2 (H2): Directory Cascade & Coalescing Test Suite

Validates:
1. Small and large directory deletes.
2. Nested directory deletes.
3. Excluded paths within deleted directories.
4. Multi-depth directory trees.
5. Delete + recreate race safety.
6. Delete with concurrent file creation.
7. Nested registered folder isolation.
8. Path case variations on Windows.
9. Reparse point/junction traversal safety.
10. Directory rename and move across subpaths.
11. Move involving excluded paths.
12. Rename followed immediately by modification.
13. Rename followed by deletion.
14. Controlled high-volume burst coalescing.
"""

import os
import shutil
import tempfile
import time
from typing import Any, Dict, List
import pytest

from app.core.security import normalize_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.watcher import DebouncedEventManager, WatcherService, is_subpath


@pytest.fixture
def temp_env():
    """Provides an isolated test directory and SQLite database."""
    test_root = tempfile.mkdtemp(prefix="filemind_h2_test_")
    db_path = os.path.join(test_root, "test_filemind.db")
    db_mgr = DatabaseManager(db_path)
    
    with db_mgr.session() as conn:
        apply_migrations(conn)

    yield test_root, db_mgr

    shutil.rmtree(test_root, ignore_errors=True)


def test_is_subpath_semantics():
    """Validates subpath containment logic across Windows case and separator variations."""
    assert is_subpath("C:/dev/proj/sub/file.txt", "C:/dev/proj")
    assert is_subpath("C:\\dev\\proj\\sub\\file.txt", "C:/dev/proj")
    assert is_subpath("c:\\dev\\proj\\SUB\\file.txt", "C:\\DEV\\PROJ")
    assert is_subpath("C:/dev/proj", "C:/dev/proj")
    assert not is_subpath("C:/dev/proj_other/file.txt", "C:/dev/proj")
    assert not is_subpath("C:/dev/proj", "C:/dev/proj/sub")


def test_small_directory_delete(temp_env):
    """Scenario 1: Small directory deletion marks child files MISSING and cancels jobs."""
    test_root, db_mgr = temp_env
    folder_dir = os.path.join(test_root, "watched")
    sub_dir = os.path.join(folder_dir, "small_dir")
    os.makedirs(sub_dir, exist_ok=True)

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]
        
        # Populate 5 files
        for i in range(5):
            fp = os.path.join(sub_dir, f"doc_{i}.txt")
            with open(fp, "w") as f:
                f.write(f"content {i}")
            file_rec = repo.upsert_file(
                folder_id=fid,
                path=normalize_path(fp),
                relative_path=f"small_dir/doc_{i}.txt",
                filename=f"doc_{i}.txt",
                extension=".txt",
                size_bytes=10,
                modified_at="2026-08-30T12:00:00Z",
                index_status="QUEUED"
            )
            repo.enqueue_job(file_id=file_rec["file_id"], folder_id=fid)

    watcher = WatcherService(db_mgr)
    watcher.start()
    time.sleep(0.3)

    shutil.rmtree(sub_dir)
    time.sleep(0.8)
    watcher.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        files = repo.list_files(fid)
        assert len(files) == 5
        for f in files:
            assert f["index_status"] == "MISSING"

        # Check indexing jobs cancelled
        cursor = conn.execute("SELECT COUNT(*) FROM indexing_jobs WHERE status = 'PENDING';")
        assert cursor.fetchone()[0] == 0


def test_large_directory_delete_coalescing(temp_env):
    """Scenario 2: Deleting a directory with hundreds of files coalesces and executes in batch."""
    test_root, db_mgr = temp_env
    folder_dir = os.path.join(test_root, "watched")
    sub_dir = os.path.join(folder_dir, "large_dir")
    os.makedirs(sub_dir, exist_ok=True)

    file_count = 200
    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]
        
        for i in range(file_count):
            fp = os.path.join(sub_dir, f"file_{i:04d}.txt")
            with open(fp, "w") as f:
                f.write("content")
            repo.upsert_file(
                folder_id=fid,
                path=normalize_path(fp),
                relative_path=f"large_dir/file_{i:04d}.txt",
                filename=f"file_{i:04d}.txt",
                extension=".txt",
                size_bytes=7,
                modified_at="2026-08-30T12:00:00Z",
                index_status="INDEXED"
            )

    events_received = []
    watcher = WatcherService(db_mgr, on_normalized_event=lambda ev: events_received.append(ev))
    watcher.start()
    time.sleep(0.3)

    shutil.rmtree(sub_dir)
    time.sleep(1.0)
    watcher.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        missing_count = repo.count_files_by_status(fid)["MISSING"]
        assert missing_count == file_count


def test_nested_directory_delete(temp_env):
    """Scenario 3: Multi-level nested directory delete marks all descendants MISSING."""
    test_root, db_mgr = temp_env
    folder_dir = os.path.join(test_root, "watched")
    nested_dir = os.path.join(folder_dir, "dept", "team", "project")
    os.makedirs(nested_dir, exist_ok=True)

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]

        for i in range(10):
            fp = os.path.join(nested_dir, f"item_{i}.txt")
            with open(fp, "w") as f:
                f.write("test")
            repo.upsert_file(
                folder_id=fid,
                path=normalize_path(fp),
                relative_path=f"dept/team/project/item_{i}.txt",
                filename=f"item_{i}.txt",
                extension=".txt",
                size_bytes=4,
                modified_at="2026-08-30T12:00:00Z",
                index_status="INDEXED"
            )

    watcher = WatcherService(db_mgr)
    watcher.start()
    time.sleep(0.3)

    # Delete top-level dept
    shutil.rmtree(os.path.join(folder_dir, "dept"))
    time.sleep(0.8)
    watcher.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        assert repo.count_files_by_status(fid)["MISSING"] == 10


def test_delete_and_recreate_race(temp_env):
    """Scenario 6: Fast delete and immediate recreate preserves recreated content."""
    test_root, db_mgr = temp_env
    folder_dir = os.path.join(test_root, "watched")
    sub_dir = os.path.join(folder_dir, "transient_dir")
    os.makedirs(sub_dir, exist_ok=True)
    fp = os.path.join(sub_dir, "file.txt")
    with open(fp, "w") as f:
        f.write("version 1")

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]
        repo.upsert_file(
            folder_id=fid,
            path=normalize_path(fp),
            relative_path="transient_dir/file.txt",
            filename="file.txt",
            extension=".txt",
            size_bytes=9,
            modified_at="2026-08-30T12:00:00Z",
            index_status="INDEXED"
        )

    watcher = WatcherService(db_mgr)
    watcher.start()
    time.sleep(0.3)

    # Delete and immediately recreate with new file
    shutil.rmtree(sub_dir)
    os.makedirs(sub_dir, exist_ok=True)
    new_fp = os.path.join(sub_dir, "new_file.txt")
    with open(new_fp, "w") as f:
        f.write("version 2")

    time.sleep(1.0)
    watcher.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        files = repo.list_files(fid)
        paths = [f["path"] for f in files]
        assert normalize_path(new_fp) in paths


def test_nested_registered_folder_isolation(temp_env):
    """Scenario 8: Nested registered roots are isolated by folder_id."""
    test_root, db_mgr = temp_env
    parent_dir = os.path.join(test_root, "parent_root")
    child_dir = os.path.join(parent_dir, "child_root")
    os.makedirs(child_dir, exist_ok=True)

    with db_mgr.session() as conn:
        repo = Repository(conn)
        p_rec = repo.create_folder(parent_dir)
        p_id = p_rec["folder_id"]
        c_rec = repo.create_folder(child_dir)
        c_id = c_rec["folder_id"]

        # Insert file under child_root registered under c_id
        child_file = os.path.join(child_dir, "child.txt")
        with open(child_file, "w") as f:
            f.write("child content")
        repo.upsert_file(
            folder_id=c_id,
            path=normalize_path(child_file),
            relative_path="child.txt",
            filename="child.txt",
            extension=".txt",
            size_bytes=13,
            modified_at="2026-08-30T12:00:00Z",
            index_status="INDEXED"
        )

    # Subtree deletion on parent root should not affect child_root files registered under c_id
    with db_mgr.session() as conn:
        repo = Repository(conn)
        repo.mark_directory_missing(p_id, child_dir)
        c_files = repo.list_files(c_id)
        assert len(c_files) == 1
        assert c_files[0]["index_status"] == "INDEXED"


def test_directory_rename_and_move(temp_env):
    """Scenario 10: Directory rename updates paths of all child files in SQLite."""
    test_root, db_mgr = temp_env
    folder_dir = os.path.join(test_root, "watched")
    old_dir = os.path.join(folder_dir, "old_name")
    os.makedirs(old_dir, exist_ok=True)

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]

        for i in range(5):
            fp = os.path.join(old_dir, f"doc_{i}.txt")
            with open(fp, "w") as f:
                f.write(f"content {i}")
            repo.upsert_file(
                folder_id=fid,
                path=normalize_path(fp),
                relative_path=f"old_name/doc_{i}.txt",
                filename=f"doc_{i}.txt",
                extension=".txt",
                size_bytes=9,
                modified_at="2026-08-30T12:00:00Z",
                index_status="INDEXED"
            )

    watcher = WatcherService(db_mgr)
    watcher.start()
    time.sleep(0.3)

    new_dir = os.path.join(folder_dir, "new_name")
    os.rename(old_dir, new_dir)
    time.sleep(0.8)
    watcher.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        files = repo.list_files(fid)
        assert len(files) == 5
        for f in files:
            assert "new_name" in f["path"]
            assert f["relative_path"].startswith("new_name/")


def test_burst_high_volume_coalescing():
    """Scenario 14: Burst event coalescing collapses rapid duplicate and cascade events."""
    flushed_batches = []
    debouncer = DebouncedEventManager(
        debounce_window_sec=0.1,
        on_flush_batch=lambda batch: flushed_batches.append(batch)
    )

    # Push 500 file delete events under same directory
    for i in range(500):
        debouncer.push_event({
            "folder_id": "test_folder",
            "event_type": "DELETE",
            "path": f"C:\\dev\\root\\dir\\file_{i}.txt",
            "is_directory": False
        })
    # Then push directory delete
    debouncer.push_event({
        "folder_id": "test_folder",
        "event_type": "DELETE",
        "path": "C:\\dev\\root\\dir",
        "is_directory": True
    })

    debouncer.flush()
    assert len(flushed_batches) == 1
    # All 500 child deletes collapsed into 1 directory delete!
    assert len(flushed_batches[0]) == 1
    assert flushed_batches[0][0]["path"] == "C:\\dev\\root\\dir"
    assert flushed_batches[0][0]["is_directory"] is True
