"""Tests for Bug 1: Discovery scan errors use dedicated record_scan_error without phantom jobs.

Verifies:
1. Repository record_scan_error updates existing file to FAILED with indexing_error.
2. Repository record_scan_error logs a SCAN_ERROR event in file_events.
3. Repository record_scan_error leaves MISSING files unchanged and returns False.
4. Repository record_scan_error does not fabricate any indexing_jobs row.
5. FilesystemScanner uses record_scan_error on PermissionError and OSError.
6. FilesystemScanner continues scanning remaining files after encountering a scan error.
"""

import os
import unittest.mock as mock
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_scan_error.db"
    db_manager = DatabaseManager(str(db_file))
    with db_manager.session() as conn:
        apply_migrations(conn)
    return db_manager


def test_repository_record_scan_error_success(test_db, tmp_path):
    "test_repository_record_scan_error_success"
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_path))
        file_path = os.path.normpath(str(tmp_path / "test_doc.txt"))
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=file_path,
            relative_path="test_doc.txt",
            filename="test_doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-04T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]

        updated = repo.record_scan_error(file_id, "Permission denied: access restricted")
        assert updated is True

        # Check file state
        refreshed = repo.get_file_by_id(file_id)
        assert refreshed["index_status"] == "FAILED"
        assert refreshed["indexing_error"] == "Permission denied: access restricted"

        # Check file_events log
        events = repo.list_events(folder["folder_id"])
        scan_events = [e for e in events if e["event_type"] == "SCAN_ERROR"]
        assert len(scan_events) == 1
        assert scan_events[0]["file_id"] == file_id
        assert scan_events[0]["path"] == file_path
        assert scan_events[0]["processing_status"] == "FAILED"

        # Verify no indexing jobs were fabricated
        jobs = repo.list_jobs()
        assert len(jobs) == 0


def test_repository_record_scan_error_ignores_missing_files(test_db, tmp_path):
    "test_repository_record_scan_error_ignores_missing_files"
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_path))
        file_path = os.path.normpath(str(tmp_path / "missing_doc.txt"))
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=file_path,
            relative_path="missing_doc.txt",
            filename="missing_doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-04T12:00:00Z",
            index_status="MISSING",
        )
        file_id = file_rec["file_id"]

        updated = repo.record_scan_error(file_id, "Access error during scan")
        assert updated is False

        refreshed = repo.get_file_by_id(file_id)
        assert refreshed["index_status"] == "MISSING"


def test_repository_record_scan_error_nonexistent_file(test_db):
    "test_repository_record_scan_error_nonexistent_file"
    with test_db.session() as conn:
        repo = Repository(conn)
        updated = repo.record_scan_error("non-existent-file-id", "Some error")
        assert updated is False


def test_discovery_scanner_permission_error_propagation(test_db, tmp_path):
    "test_discovery_scanner_permission_error_propagation"
    scan_dir = tmp_path / "scan_subfolder"
    scan_dir.mkdir()
    file_a = scan_dir / "file_a.txt"
    file_b = scan_dir / "file_b.txt"
    file_a.write_text("content A", encoding="utf-8")
    file_b.write_text("content B", encoding="utf-8")

    file_a_path = os.path.normpath(str(file_a))
    file_b_path = os.path.normpath(str(file_b))

    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(scan_dir))
        folder_id = folder["folder_id"]

        # Pre-seed file_a in DB
        file_a_rec = repo.upsert_file(
            folder_id=folder_id,
            path=file_a_path,
            relative_path="file_a.txt",
            filename="file_a.txt",
            extension=".txt",
            size_bytes=len("content A"),
            modified_at="2026-09-04T12:00:00Z",
            index_status="INDEXED",
        )
        file_a_id = file_a_rec["file_id"]

        scanner = FilesystemScanner(repo)

        # mock os.stat only for file_a
        original_stat = os.stat

        def mock_stat(path, *args, **kwargs):
            norm = os.path.normpath(str(path)).lower()
            if norm == file_a_path.lower():
                raise PermissionError(f"[WinError 5] Access is denied: {path}")
            return original_stat(path, *args, **kwargs)

        with mock.patch("os.stat", side_effect=mock_stat):
            result = scanner.scan_folder(folder_id)

        # Scanner should report error for file_a and discover file_b
        assert len(result.errors) == 1
        assert result.new_files == 1  # file_b was newly discovered

        # file_a must be updated to FAILED with indexing_error populated
        refreshed_a = repo.get_file_by_id(file_a_id)
        assert refreshed_a["index_status"] == "FAILED"
        assert "Access error during scan" in refreshed_a["indexing_error"]
        assert "Access is denied" in refreshed_a["indexing_error"]

        # file_b must be QUEUED with an enqueued job
        file_b_rec = repo.get_file_by_path(file_b_path)
        assert file_b_rec is not None
        assert file_b_rec["index_status"] == "QUEUED"

        # Verify no phantom system-scan job exists
        jobs = repo.list_jobs()
        job_ids = [j["job_id"] for j in jobs]
        assert "system-scan" not in job_ids

        # Verify SCAN_ERROR event is recorded
        events = repo.list_events(folder_id)
        scan_events = [e for e in events if e["event_type"] == "SCAN_ERROR"]
        assert len(scan_events) == 1
        assert scan_events[0]["file_id"] == file_a_id


def test_discovery_scanner_oserror_propagation(test_db, tmp_path):
    "test_discovery_scanner_oserror_propagation"
    scan_dir = tmp_path / "scan_subfolder_oserror"
    scan_dir.mkdir()
    file_c = scan_dir / "file_c.txt"
    file_c.write_text("content C", encoding="utf-8")
    file_c_path = os.path.normpath(str(file_c))

    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(scan_dir))
        folder_id = folder["folder_id"]

        file_c_rec = repo.upsert_file(
            folder_id=folder_id,
            path=file_c_path,
            relative_path="file_c.txt",
            filename="file_c.txt",
            extension=".txt",
            size_bytes=len("content C"),
            modified_at="2026-09-04T12:00:00Z",
            index_status="INDEXED",
        )
        file_c_id = file_c_rec["file_id"]

        scanner = FilesystemScanner(repo)

        original_stat = os.stat
        def mock_stat_c(path, *args, **kwargs):
            norm = os.path.normpath(str(path)).lower()
            if norm == file_c_path.lower():
                raise OSError("I/O device error")
            return original_stat(path, *args, **kwargs)

        with mock.patch("os.stat", side_effect=mock_stat_c):
            result = scanner.scan_folder(folder_id)

        assert len(result.errors) == 1
        refreshed_c = repo.get_file_by_id(file_c_id)
        assert refreshed_c["index_status"] == "FAILED"
        assert "I/O device error" in refreshed_c["indexing_error"]

        # SCAN_ERROR event logged
        events = repo.list_events(folder_id)
        assert any(
            e["event_type"] == "SCAN_ERROR" and e["file_id"] == file_c_id for e in events
        )

