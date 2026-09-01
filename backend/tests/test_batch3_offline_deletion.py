"""Regression tests for Bug #11: Offline Deletion Reconciliation in Scanner."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner


def test_offline_deletion_reconciliation():
    db_file = os.path.join(tempfile.gettempdir(), f"test_offline_del_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            file1 = os.path.join(tmp_root, "file1.txt")
            file2 = os.path.join(tmp_root, "file2.txt")
            with open(file1, "w", encoding="utf-8") as f:
                f.write("File 1 contents")
            with open(file2, "w", encoding="utf-8") as f:
                f.write("File 2 contents")

            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root, integrity_mode="NORMAL")
                folder_id = folder["folder_id"]

            # Initial scan: indexes both files
            with db.session() as conn:
                scanner = FilesystemScanner(Repository(conn))
                res1 = scanner.scan_folder(folder_id)
                assert res1.total_scanned == 2
                assert res1.new_files == 2
                assert res1.stale_files == 0

            # Simulate worker completing jobs and marking files as INDEXED
            with db.session() as conn:
                repo = Repository(conn)
                f1_rec = repo.get_file_by_path(file1)
                f2_rec = repo.get_file_by_path(file2)
                assert f1_rec["index_status"] in ("DISCOVERED", "QUEUED")
                assert f2_rec["index_status"] in ("DISCOVERED", "QUEUED")
                repo.complete_job(res1.enqueued_job_ids[0], f1_rec["file_id"], sha256="hash1", final_status="INDEXED")
                repo.complete_job(res1.enqueued_job_ids[1], f2_rec["file_id"], sha256="hash2", final_status="INDEXED")

            # Simulate file2 deleted while FileMind is closed (offline deletion)
            os.remove(file2)

            # Second scan: file2 is missing on disk -> reconciled as stale
            with db.session() as conn:
                scanner = FilesystemScanner(Repository(conn))
                res2 = scanner.scan_folder(folder_id)
                assert res2.total_scanned == 1
                assert res2.unchanged_files == 1
                assert res2.stale_files == 1
                assert len(res2.enqueued_job_ids) == 1  # DELETE_CLEANUP enqueued

            # Verify DB state after reconciliation
            with db.session() as conn:
                repo = Repository(conn)
                f1_rec = repo.get_file_by_path(file1)
                f2_rec = repo.get_file_by_path(file2)
                assert f1_rec["index_status"] == "INDEXED"
                assert f2_rec["index_status"] == "MISSING"

                # Check DELETE_CLEANUP job was queued
                jobs = repo.list_jobs(status="PENDING")
                cleanup_jobs = [j for j in jobs if j["job_type"] == "DELETE_CLEANUP" and j["file_id"] == f2_rec["file_id"]]
                assert len(cleanup_jobs) == 1
    finally:
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
