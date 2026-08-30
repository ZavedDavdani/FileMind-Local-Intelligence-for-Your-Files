"""Change detection and streaming SHA-256 test suite."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.engine.hasher import compute_file_sha256


def test_streaming_sha256_computation():
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write("Hello FileMind Phase 1 Streaming Hash!")
        temp_path = f.name

    try:
        digest, err = compute_file_sha256(temp_path)
        assert err is None
        assert digest is not None
        assert len(digest) == 64
        import hashlib
        expected = hashlib.sha256("Hello FileMind Phase 1 Streaming Hash!".encode("utf-8")).hexdigest()
        assert digest == expected
    finally:
        os.remove(temp_path)


def test_sha256_missing_file_handling():
    digest, err = compute_file_sha256(r"C:\non_existent_file_path_12345.txt")
    assert digest is None
    assert "does not exist" in err


def test_change_detection_normal_vs_strict():
    db_file = os.path.join(tempfile.gettempdir(), f"test_cd_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            file1 = os.path.join(tmp_root, "doc.txt")
            with open(file1, "w", encoding="utf-8") as f:
                f.write("Initial content")

            with db.session() as conn:
                repo = Repository(conn)
                f_norm = repo.create_folder(tmp_root, integrity_mode="NORMAL")
                norm_id = f_norm["folder_id"]

            with db.session() as conn:
                scanner = FilesystemScanner(Repository(conn))
                # 1. Initial Scan -> New file queued
                res1 = scanner.scan_folder(norm_id)
                assert res1.total_scanned == 1
                assert res1.new_files == 1
                assert len(res1.enqueued_job_ids) == 1

            # Simulate job completion
            with db.session() as conn:
                repo = Repository(conn)
                f_rec = repo.get_file_by_path(file1)
                digest, _ = compute_file_sha256(file1)
                repo.complete_job(res1.enqueued_job_ids[0], f_rec["file_id"], sha256=digest)

            # 2. Second Scan (Unchanged) -> Fast path skips rehash
            with db.session() as conn:
                scanner = FilesystemScanner(Repository(conn))
                res2 = scanner.scan_folder(norm_id)
                assert res2.total_scanned == 1
                assert res2.unchanged_files == 1
                assert res2.modified_files == 0
                assert len(res2.enqueued_job_ids) == 0

            # 3. Modify File -> Detected as modified and re-queued
            time.sleep(0.05)
            with open(file1, "w", encoding="utf-8") as f:
                f.write("Updated content version 2")

            with db.session() as conn:
                scanner = FilesystemScanner(Repository(conn))
                res3 = scanner.scan_folder(norm_id)
                assert res3.modified_files == 1
                assert len(res3.enqueued_job_ids) == 1

            # 4. Strict Mode Scan -> Forces rehash job even if timestamps are touched
            with db.session() as conn:
                repo = Repository(conn)
                repo.update_folder(norm_id, integrity_mode="STRICT")
                scanner = FilesystemScanner(repo)
                res4 = scanner.scan_folder(norm_id, force_strict_rehash=True)
                assert len(res4.enqueued_job_ids) == 1
    finally:
        try:
            if os.path.exists(db_file):
                os.remove(db_file)
        except Exception:
            pass
