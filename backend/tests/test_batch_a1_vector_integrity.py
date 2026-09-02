"""Tests for Batch A1: Vector-Layer Integrity & Hardening.

Verifies:
1. DatabaseManager explicitly raises RuntimeError when sqlite-vec loading fails.
2. DELETE_CLEANUP failure in vector deletion rolls back chunks and fails/schedules retry for the job (never completed).
3. DELETE_CLEANUP permanent failure after max retries marks job as FAILED.
4. DELETE_CLEANUP success deletes vectors and relational chunks and completes normally.
5. Repository.delete_folder fails and does not delete folder if vector cleanup fails.
6. Repository.delete_folder successfully purges chunk_vectors.
7. Repository.delete_file cleans up chunk_vectors and files.
8. Repository.delete_file fails and does not delete file record if vector cleanup fails.
9. Deletion operations are idempotent and deterministic on repeated invocation.
10. REQUIRES_OCR purges vectors before chunks and completes with SKIPPED status.
"""

import os
import sqlite3
import tempfile
import unittest.mock as mock
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.queue import JobQueue
from app.engine.worker import WorkerPool
from app.intelligence.chunker.provenance import ChunkProvenance
from app.retrieval.vector_store import SqliteVecStore


class FailingConnectionProxy:
    """Delegating proxy for sqlite3.Connection that injects operational failures on matching SQL."""

    def __init__(self, real_conn: sqlite3.Connection, fail_pattern: str = "DELETE FROM chunk_vectors"):
        self._real_conn = real_conn
        self._fail_pattern = fail_pattern

    def execute(self, sql: str, *args, **kwargs):
        if self._fail_pattern in sql:
            raise sqlite3.OperationalError(f"Simulated failure on pattern: {self._fail_pattern}")
        return self._real_conn.execute(sql, *args, **kwargs)

    def executemany(self, sql: str, *args, **kwargs):
        if self._fail_pattern in sql:
            raise sqlite3.OperationalError(f"Simulated failure on pattern: {self._fail_pattern}")
        return self._real_conn.executemany(sql, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._real_conn, name)


@pytest.fixture
def integrity_test_env():
    """Sets up an isolated SQLite database with migrations and sample folder/file/chunks/vectors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_integrity.db")
        db = DatabaseManager(db_path)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            vec_store = SqliteVecStore(conn, dimension=4)

            # Create folder
            folder = repo.create_folder(tmp_dir)
            fid = folder["folder_id"]

            # Create file
            file_path = os.path.join(tmp_dir, "doc1.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Test document content for vector integrity verification.")

            f_rec = repo.upsert_file(
                folder_id=fid,
                path=file_path,
                relative_path="doc1.txt",
                filename="doc1.txt",
                extension=".txt",
                size_bytes=os.path.getsize(file_path),
                modified_at="2026-09-02T10:00:00Z",
                file_id="f_doc1",
            )

            # Create chunk
            chunk = ChunkProvenance(
                chunk_id="chk_doc1_1",
                file_id="f_doc1",
                source_file="doc1.txt",
                source_path=file_path,
                content="Test document content for vector integrity verification.",
                content_hash="hash_doc1_1",
                chunk_index=0,
            )
            repo.replace_file_chunks("f_doc1", [chunk])

            # Insert vector
            vec_store.upsert_vectors([
                {"chunk_id": "chk_doc1_1", "file_id": "f_doc1", "embedding": [1.0, 0.0, 0.0, 0.0]}
            ])

        yield {
            "db": db,
            "tmp_dir": tmp_dir,
            "folder_id": fid,
            "file_id": "f_doc1",
            "chunk_id": "chk_doc1_1",
            "file_path": file_path,
        }


def test_1_sqlite_vec_load_failure_raises_explicit_runtime_error():
    """Verifies that failure to load sqlite_vec extension raises an explicit RuntimeError."""
    db = DatabaseManager(":memory:")
    with mock.patch("sqlite_vec.load", side_effect=Exception("Simulated DLL loading failure")):
        with pytest.raises(RuntimeError, match="Failed to load sqlite-vec extension: Simulated DLL loading failure"):
            db.get_connection()


def test_2_delete_cleanup_vector_failure_rolls_back_and_fails_job(integrity_test_env):
    """Verifies that DELETE_CLEANUP job does NOT complete if vector deletion fails, and chunks are not partially deleted."""
    env = integrity_test_env
    db = env["db"]
    queue = JobQueue(db)
    worker = WorkerPool(db)

    with db.session() as conn:
        repo = Repository(conn)
        job = repo.enqueue_job(file_id=env["file_id"], folder_id=env["folder_id"], job_type="DELETE_CLEANUP")

    claimed = queue.claim_job()
    assert claimed is not None
    assert claimed["job_id"] == job["job_id"]

    # Inject failure into delete_by_file_id
    with mock.patch.object(SqliteVecStore, "delete_by_file_id", side_effect=sqlite3.OperationalError("Simulated disk error on vector table")):
        worker._process_job(claimed)

    # Verify job was NOT marked COMPLETED
    with db.session() as conn:
        repo = Repository(conn)
        status_counts = repo.count_jobs_by_status()
        assert status_counts["COMPLETED"] == 0

        # Job error is recorded
        jobs = repo.list_jobs()
        assert any("Simulated disk error" in (j.get("error") or "") for j in jobs)

        # Chunks must NOT have been partially deleted due to transaction rollback
        chunks = repo.get_chunks_by_file(env["file_id"])
        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == env["chunk_id"]

        # Vectors must still be intact
        vec_store = SqliteVecStore(conn, dimension=4)
        assert vec_store.count() == 1


def test_3_delete_cleanup_max_retries_marks_permanent_failure(integrity_test_env):
    """Verifies that DELETE_CLEANUP job transitions to FAILED when max retries are exceeded."""
    env = integrity_test_env
    db = env["db"]
    queue = JobQueue(db)
    worker = WorkerPool(db)

    with db.session() as conn:
        repo = Repository(conn)
        job = repo.enqueue_job(file_id=env["file_id"], folder_id=env["folder_id"], job_type="DELETE_CLEANUP")

    claimed = queue.claim_job()
    assert claimed is not None
    claimed["attempts"] = 3  # MAX_RETRY_ATTEMPTS reached

    # Inject failure into delete_by_file_id
    with mock.patch.object(SqliteVecStore, "delete_by_file_id", side_effect=sqlite3.OperationalError("Persistent storage error")):
        worker._process_job(claimed)

    with db.session() as conn:
        repo = Repository(conn)
        status_counts = repo.count_jobs_by_status()
        assert status_counts["COMPLETED"] == 0
        assert status_counts["FAILED"] == 1


def test_4_delete_cleanup_success_purges_vectors_and_chunks(integrity_test_env):
    """Verifies that successful DELETE_CLEANUP deletes both vectors and relational chunks and completes normally."""
    env = integrity_test_env
    db = env["db"]
    queue = JobQueue(db)
    worker = WorkerPool(db)

    with db.session() as conn:
        repo = Repository(conn)
        job = repo.enqueue_job(file_id=env["file_id"], folder_id=env["folder_id"], job_type="DELETE_CLEANUP")

    claimed = queue.claim_job()
    assert claimed is not None

    worker._process_job(claimed)

    with db.session() as conn:
        repo = Repository(conn)
        status_counts = repo.count_jobs_by_status()
        assert status_counts["COMPLETED"] == 1
        assert status_counts["FAILED"] == 0

        # Chunks purged
        assert len(repo.get_chunks_by_file(env["file_id"])) == 0

        # Vectors purged
        vec_store = SqliteVecStore(conn, dimension=4)
        assert vec_store.count() == 0


def test_5_delete_folder_fails_and_rolls_back_if_vector_cleanup_fails(integrity_test_env):
    """Verifies that delete_folder() raises an exception and does NOT delete folder if vector cleanup fails."""
    env = integrity_test_env
    db = env["db"]

    with db.session() as conn:
        proxy_conn = FailingConnectionProxy(conn, fail_pattern="DELETE FROM chunk_vectors")
        repo = Repository(proxy_conn)

        with pytest.raises(sqlite3.OperationalError, match="Simulated failure on pattern"):
            repo.delete_folder(env["folder_id"])

    # Verify folder was NOT deleted
    with db.session() as conn:
        repo = Repository(conn)
        folder = repo.get_folder(env["folder_id"])
        assert folder is not None
        assert folder["folder_id"] == env["folder_id"]
        assert len(repo.get_chunks_by_file(env["file_id"])) == 1
        vec_store = SqliteVecStore(conn, dimension=4)
        assert vec_store.count() == 1


def test_6_delete_folder_success_purges_all_vectors(integrity_test_env):
    """Verifies that delete_folder() successfully removes chunk_vectors along with folder, files, and chunks."""
    env = integrity_test_env
    db = env["db"]

    with db.session() as conn:
        repo = Repository(conn)
        vec_store = SqliteVecStore(conn, dimension=4)
        assert vec_store.count() == 1

        success = repo.delete_folder(env["folder_id"])
        assert success is True
        assert vec_store.count() == 0
        assert repo.get_folder(env["folder_id"]) is None


def test_7_delete_file_cleans_up_vectors_and_file_record(integrity_test_env):
    """Verifies that delete_file() removes chunk_vectors and file record atomically."""
    env = integrity_test_env
    db = env["db"]

    with db.session() as conn:
        repo = Repository(conn)
        vec_store = SqliteVecStore(conn, dimension=4)
        assert vec_store.count() == 1

        success = repo.delete_file(env["file_id"])
        assert success is True

        # Vector purged
        assert vec_store.count() == 0
        # File purged
        assert repo.get_file_by_id(env["file_id"]) is None
        # Chunks cascaded
        assert len(repo.get_chunks_by_file(env["file_id"])) == 0


def test_8_delete_file_fails_if_vector_cleanup_fails(integrity_test_env):
    """Verifies that delete_file() raises if vector cleanup fails, preserving the file record."""
    env = integrity_test_env
    db = env["db"]

    with db.session() as conn:
        proxy_conn = FailingConnectionProxy(conn, fail_pattern="DELETE FROM chunk_vectors")
        repo = Repository(proxy_conn)

        with pytest.raises(sqlite3.OperationalError, match="Simulated failure on pattern"):
            repo.delete_file(env["file_id"])

    # Verify file and vector remain intact
    with db.session() as conn:
        repo = Repository(conn)
        assert repo.get_file_by_id(env["file_id"]) is not None
        vec_store = SqliteVecStore(conn, dimension=4)
        assert vec_store.count() == 1


def test_9_repeated_deletion_is_idempotent_and_deterministic(integrity_test_env):
    """Verifies that repeatedly deleting already deleted folders/files is safe and returns False."""
    env = integrity_test_env
    db = env["db"]

    with db.session() as conn:
        repo = Repository(conn)
        # First deletion
        assert repo.delete_file(env["file_id"]) is True
        # Second deletion of same file -> False, no crash
        assert repo.delete_file(env["file_id"]) is False

        # First folder deletion
        assert repo.delete_folder(env["folder_id"]) is True
        # Second folder deletion of same folder -> False, no crash
        assert repo.delete_folder(env["folder_id"]) is False


def test_10_ocr_purge_stale_vectors_before_chunks(integrity_test_env):
    """Verifies that when a document is detected as REQUIRES_OCR, worker purges stale vectors and chunks."""
    env = integrity_test_env
    db = env["db"]
    queue = JobQueue(db)
    worker = WorkerPool(db)

    with db.session() as conn:
        repo = Repository(conn)
        # Enqueue chunk generation job for the file that has existing chunks/vectors
        job = repo.enqueue_job(file_id=env["file_id"], folder_id=env["folder_id"], job_type="CHUNK_GENERATION")

    claimed = queue.claim_job()
    assert claimed is not None

    # Mock parser returning doc with REQUIRES_OCR quality assessment
    mock_qa = mock.MagicMock()
    mock_qa.status = "REQUIRES_OCR"
    mock_qa.reason_codes = ["SCAN_ONLY"]
    mock_qa.to_json.return_value = '{"status": "REQUIRES_OCR", "reason_codes": ["SCAN_ONLY"]}'

    mock_doc = mock.MagicMock()
    mock_doc.quality_assessment = mock_qa

    mock_parser = mock.MagicMock()
    mock_parser.parser_version = "1.0.0"
    mock_parser.parse.return_value = mock_doc

    with mock.patch("app.intelligence.parsers.registry.default_parser_registry.get_parser_for_file", return_value=mock_parser):
        worker._process_job(claimed)

    with db.session() as conn:
        repo = Repository(conn)
        # Status should be SKIPPED
        f_rec = repo.get_file_by_id(env["file_id"])
        assert f_rec["index_status"] == "SKIPPED"
        assert "REQUIRES_OCR" in (f_rec["indexing_error"] or "")

        # Stale chunks and vectors must be purged
        assert len(repo.get_chunks_by_file(env["file_id"])) == 0
        vec_store = SqliteVecStore(conn, dimension=4)
        assert vec_store.count() == 0

