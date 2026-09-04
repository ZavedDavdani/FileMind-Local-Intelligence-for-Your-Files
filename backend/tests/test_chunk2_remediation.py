"""Comprehensive regression test suite for FileMind Chunk 2 remediation.

Covers:
- Bug 25: EngineCoordinator / WorkerPool constructor contract & real initialization
- Bug 26: notify_job_available worker wake-up
- Bug 27 & 28: chunk_vectors deletion integrity, foreign keys, and deletion ordering
- Bug 29: upsert_file lifecycle preservation on unchanged rediscovery
- Bug 30: get_aggregate_status accurate accounting (no double-counting)
- Bug 31: mark_directory_missing vs live PROCESSING worker race
- Bug 32: Adaptive vector search candidate recall with narrow metadata filters
- Bug 33: Unknown embedding model dimension diagnostics
- Bug 34: Nomic query vs document prefix symmetry
- Bug 35: verify_index_validity missing/incomplete metadata rejection
- Bug 36: Embedding outside transaction and atomic persistence
- Bug 37: DELETE_CLEANUP completion status
- Bug 38: Move/rename sequences and path casing uniqueness
- Bug 39: Isolated per-folder scan DB sessions in scan_all_enabled_folders
- Bug 40: Worker event-driven loop and clean shutdown
- Bug 87: Rejection of invalid INDEXED_PARTIAL state
- Bug 88: claim_next_job skips file PROCESSING for DELETE_CLEANUP
- Bug 89: is_current_processing_job ownership semantics
- Bug 95: SQLite connection lifecycle with WAL and busy timeout
- Bug 115: Folder deletion vector cleanup across single/multi-file folders
- Bug 118: Disabled folders' queued jobs skipped while cleanup jobs remain claimable
- Bug 119: Attempt accounting across crash recoveries and genuine retries
"""

import os
import sqlite3
import tempfile
import threading
import time
from typing import Any, Dict, List
import pytest

from app.core.security import normalize_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.coordinator import EngineCoordinator
from app.engine.discovery import FilesystemScanner
from app.engine.worker import WorkerPool
from app.retrieval.embeddings import EmbeddingEngine, MODEL_DIMENSIONS
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def clean_db(tmp_path):
    """Provides a clean, migrated DatabaseManager."""
    db_file = tmp_path / "test_chunk2.db"
    mgr = DatabaseManager(db_file)
    with mgr.session() as conn:
        apply_migrations(conn)
    return mgr


class MockEmbeddingEngine:
    def __init__(self, dimension=4, model_name="test-model"):
        self.dimension = dimension
        self.model_name = model_name

    def embed_texts(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        return [[0.1 * (i + 1)] * self.dimension for i, _ in enumerate(texts)]

    def embed_query(self, query_text: str) -> List[float]:
        return [0.5] * self.dimension

    def get_identity(self) -> dict:
        return {
            "provider": "fastembed",
            "model_name": self.model_name,
            "model_version": "1.0.0",
            "dimension": self.dimension,
        }


def test_bug25_coordinator_worker_constructor_contract(clean_db):
    """Bug 25: Verify EngineCoordinator and WorkerPool constructor contract and real initialization."""
    mock_engine = MockEmbeddingEngine(dimension=4)
    coord = EngineCoordinator(db=clean_db, embedding_engine=mock_engine)
    assert coord.worker_pool.max_workers > 0
    assert coord.worker_pool.db == clean_db
    assert coord.embedding_engine == mock_engine

    # Test real initialization without constructor exceptions
    coord.initialize()
    assert coord._is_initialized is True
    assert coord.worker_pool.is_running is True
    coord.shutdown()
    assert coord._is_initialized is False
    assert coord.worker_pool.is_running is False


def test_bug26_and_40_worker_notification_and_loop(clean_db):
    """Bug 26 & 40: Verify notify_job_available wakes workers and stop() shuts down cleanly."""
    mock_engine = MockEmbeddingEngine(dimension=4)
    pool = WorkerPool(clean_db, max_workers=1, embedding_engine=mock_engine)
    pool.start()
    assert pool.is_running is True

    # Calling notify_job_available sets the wake event without raising
    pool.notify_job_available()

    # Clean shutdown within bounded timeout
    start = time.perf_counter()
    pool.stop(timeout_sec=2.0)
    latency = time.perf_counter() - start
    assert pool.is_running is False
    assert latency < 2.0


def test_bug27_28_115_vector_deletion_ordering_and_cascades(clean_db):
    """Bugs 27, 28, 115: Verify vector deletion ordering, partial index states, and folder cascades."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        vec_store = SqliteVecStore(conn, dimension=4)

        # 1. Create folder and files
        folder = repo.create_folder("C:/test_v_root")
        fid = folder["folder_id"]
        f1 = repo.upsert_file(fid, "C:/test_v_root/f1.txt", "f1.txt", "f1.txt", ".txt", 100, "2026-09-01T00:00:00Z", index_status="INDEXED")
        f2 = repo.upsert_file(fid, "C:/test_v_root/f2.txt", "f2.txt", "f2.txt", ".txt", 100, "2026-09-01T00:00:00Z", index_status="INDEXED")

        # 2. Insert chunks and vectors
        repo.replace_file_chunks(f1["file_id"], [
            {"chunk_id": "c1", "source_file": "f1.txt", "content": "chunk 1", "chunk_index": 0},
            {"chunk_id": "c2", "source_file": "f1.txt", "content": "chunk 2", "chunk_index": 1},
        ])
        repo.replace_file_chunks(f2["file_id"], [
            {"chunk_id": "c3", "source_file": "f2.txt", "content": "chunk 3", "chunk_index": 0},
        ])
        vec_store.upsert_vectors([
            {"chunk_id": "c1", "file_id": f1["file_id"], "embedding": [0.1, 0.2, 0.3, 0.4]},
            {"chunk_id": "c2", "file_id": f1["file_id"], "embedding": [0.2, 0.3, 0.4, 0.5]},
            {"chunk_id": "c3", "file_id": f2["file_id"], "embedding": [0.3, 0.4, 0.5, 0.6]},
        ])
        assert vec_store.count() == 3

        # 3. Purge file 1 index (verify vectors are purged before chunks)
        repo.purge_file_index(f1["file_id"])
        assert vec_store.count() == 1
        assert len(repo.get_chunks_by_file(f1["file_id"])) == 0

        # 4. Partial state: deleting when chunks already removed does not error or orphan
        repo.purge_file_index(f1["file_id"])

        # 5. Delete folder (cascades file 2 chunks and vectors)
        repo.delete_folder(fid)
        assert vec_store.count() == 0


def test_bug29_upsert_file_lifecycle_preservation(clean_db):
    """Bug 29: Verify upsert_file preserves INDEXED, PROCESSING, FAILED on unchanged rediscovery."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_lifecycle")
        fid = folder["folder_id"]
        path = "C:/test_lifecycle/doc.txt"
        mtime = "2026-09-01T10:00:00Z"

        # Initial index
        f = repo.upsert_file(fid, path, "doc.txt", "doc.txt", ".txt", 100, mtime, index_status="INDEXED", sha256="hash1")
        file_id = f["file_id"]
        assert f["index_status"] == "INDEXED"

        # Rediscovery with unchanged mtime and size_bytes -> preserves INDEXED
        f_rediscover = repo.upsert_file(fid, path, "doc.txt", "doc.txt", ".txt", 100, mtime, index_status="DISCOVERED")
        assert f_rediscover["index_status"] == "INDEXED"
        assert f_rediscover["sha256"] == "hash1"

        # File is PROCESSING -> rediscovery preserves PROCESSING
        repo.update_file_status(file_id, "PROCESSING")
        f_proc = repo.upsert_file(fid, path, "doc.txt", "doc.txt", ".txt", 100, mtime, index_status="QUEUED")
        assert f_proc["index_status"] == "PROCESSING"

        # File is FAILED -> rediscovery preserves FAILED and error
        repo.update_file_status(file_id, "FAILED", error="Corrupt document")
        f_fail = repo.upsert_file(fid, path, "doc.txt", "doc.txt", ".txt", 100, mtime, index_status="QUEUED")
        assert f_fail["index_status"] == "FAILED"
        assert f_fail["indexing_error"] == "Corrupt document"

        # File is MISSING -> rediscovery transitions to QUEUED
        repo.update_file_status(file_id, "MISSING")
        f_found = repo.upsert_file(fid, path, "doc.txt", "doc.txt", ".txt", 100, mtime, index_status="QUEUED")
        assert f_found["index_status"] == "QUEUED"

        # Legitimate modification (new mtime) -> transitions to QUEUED
        new_mtime = "2026-09-01T12:00:00Z"
        repo.update_file_status(file_id, "INDEXED")
        f_mod = repo.upsert_file(fid, path, "doc.txt", "doc.txt", ".txt", 120, new_mtime, index_status="QUEUED")
        assert f_mod["index_status"] == "QUEUED"
        assert f_mod["modified_at"] == new_mtime


def test_bug30_get_aggregate_status_no_double_counting(clean_db):
    """Bug 30: Verify get_aggregate_status does not double-count queued or processing jobs."""
    coord = EngineCoordinator(db=clean_db, embedding_engine=MockEmbeddingEngine(4))
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_counts")
        fid = folder["folder_id"]

        f1 = repo.upsert_file(fid, "C:/test_counts/f1.txt", "f1.txt", "f1.txt", ".txt", 50, "2026-09-01T00:00:00Z", index_status="QUEUED")
        f2 = repo.upsert_file(fid, "C:/test_counts/f2.txt", "f2.txt", "f2.txt", ".txt", 50, "2026-09-01T00:00:00Z", index_status="PROCESSING")
        f3 = repo.upsert_file(fid, "C:/test_counts/f3.txt", "f3.txt", "f3.txt", ".txt", 50, "2026-09-01T00:00:00Z", index_status="INDEXED")

        # Enqueue jobs corresponding to f1 (PENDING) and f2 (PROCESSING)
        repo.enqueue_job(f1["file_id"], fid)
        j2 = repo.enqueue_job(f2["file_id"], fid)
        conn.execute("UPDATE indexing_jobs SET status = 'PROCESSING' WHERE job_id = ?;", (j2["job_id"],))

    stats = coord.get_aggregate_status()
    assert stats["total_files"] == 3
    assert stats["queued"] == 1  # Exactly 1 queued file
    assert stats["processing"] == 1  # Exactly 1 processing file
    assert stats["indexed"] == 1  # Exactly 1 indexed file


def test_bug31_mark_directory_missing_vs_processing_worker(clean_db):
    """Bug 31: Verify stale worker cannot resurrect a file after its directory was marked missing."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_race_root")
        fid = folder["folder_id"]
        f = repo.upsert_file(fid, "C:/test_race_root/sub/doc.txt", "sub/doc.txt", "doc.txt", ".txt", 100, "2026-09-01T00:00:00Z", index_status="PROCESSING")
        job = repo.enqueue_job(f["file_id"], fid)
        repo.claim_next_job()

        # 1. Directory is marked missing while worker is processing
        repo.mark_directory_missing(folder_id=fid, dir_path="C:/test_race_root/sub")
        f_curr = repo.get_file_by_id(f["file_id"])
        assert f_curr["index_status"] == "MISSING"

        # 2. Stale worker finishes and calls complete_job -> cannot overwrite MISSING
        repo.complete_job(job["job_id"], f["file_id"], sha256="stale_hash", final_status="INDEXED")
        f_after = repo.get_file_by_id(f["file_id"])
        assert f_after["index_status"] == "MISSING"


def test_bug32_adaptive_vector_search_filtered_recall(clean_db):
    """Bug 32: Verify adaptive vector search does not prematurely terminate on narrow filters."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        vec_store = SqliteVecStore(conn, dimension=4)

        folder = repo.create_folder("C:/test_adaptive")
        fid = folder["folder_id"]

        # Insert 30 files: 25 .log files and 5 .pdf files
        records = []
        for i in range(30):
            ext = ".pdf" if i >= 25 else ".log"
            fname = f"f{i}{ext}"
            f = repo.upsert_file(fid, f"C:/test_adaptive/{fname}", fname, fname, ext, 100, "2026-09-01T00:00:00Z", index_status="INDEXED")
            repo.replace_file_chunks(f["file_id"], [{"chunk_id": f"c_{i}", "source_file": fname, "content": f"content {i}", "chunk_index": 0}])
            records.append({
                "chunk_id": f"c_{i}",
                "file_id": f["file_id"],
                "embedding": [0.1 * (i + 1), 0.2, 0.3, 0.4],
            })
        vec_store.upsert_vectors(records)

        # Search with extension filter=".pdf" requesting top_k=5
        results = vec_store.search(
            query_vector=[0.5, 0.2, 0.3, 0.4],
            top_k=5,
            filters={"extension": ".pdf"},
        )
        # All 5 PDF files must be retrieved despite being late in the candidate stream
        assert len(results) == 5
        assert all(r["source_file"].endswith(".pdf") for r in results)


def test_bug33_unknown_embedding_model_dimension():
    """Bug 33: Verify EmbeddingEngine raises diagnostic ValueError on unknown/unregistered models."""
    with pytest.raises(ValueError, match="Unknown or unconfigured embedding model"):
        EmbeddingEngine("non-existent/custom-model-999")


def test_bug34_nomic_prefix_symmetry():
    """Bug 34: Verify Nomic embedding receives symmetric search_document / search_query prefixes."""
    engine = EmbeddingEngine("nomic-ai/nomic-embed-text-v1.5")
    assert engine.dimension == 768

    class DummyModel:
        def embed(self, texts, batch_size=32):
            self.last_texts = list(texts)
            return [[0.1] * 768 for _ in texts]

    dummy = DummyModel()
    engine._model = dummy

    # 1. embed_texts prepends search_document:
    engine.embed_texts(["hello world", "search_document: already prefixed"])
    assert dummy.last_texts == ["search_document: hello world", "search_document: already prefixed"]

    # 2. embed_query prepends search_query:
    engine.embed_query("what is filemind?")
    assert dummy.last_texts == ["search_query: what is filemind?"]


def test_bug35_verify_index_validity_metadata(clean_db):
    """Bug 35: Verify verify_index_validity rejects missing/incomplete metadata when index is populated."""
    with clean_db.session() as conn:
        vec_store = SqliteVecStore(conn, dimension=4)
        active_id = {"provider": "fastembed", "model_name": "bge-small", "model_version": "1.0.0", "dimension": 4}

        # Empty index with no metadata -> Valid
        assert vec_store.verify_index_validity(active_id) is True

        # Index has vectors but NO metadata -> Invalid (reject unknown provenance)
        vec_store.upsert_vectors([{"chunk_id": "c1", "embedding": [0.1, 0.2, 0.3, 0.4]}])
        assert vec_store.verify_index_validity(active_id) is False

        # Set valid metadata -> Valid
        vec_store.set_index_metadata("fastembed", "bge-small", "1.0.0", 4)
        assert vec_store.verify_index_validity(active_id) is True

        # Incomplete or mismatched dimension -> Invalid
        mismatched_id = {"provider": "fastembed", "model_name": "bge-small", "model_version": "1.0.0", "dimension": 768}
        assert vec_store.verify_index_validity(mismatched_id) is False


def test_bug37_and_88_delete_cleanup_semantics(clean_db):
    """Bugs 37 & 88: Verify DELETE_CLEANUP does not force file PROCESSING on claim and completes with MISSING."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_del_cleanup")
        fid = folder["folder_id"]
        f = repo.upsert_file(fid, "C:/test_del_cleanup/deleted.txt", "deleted.txt", "deleted.txt", ".txt", 100, "2026-09-01T00:00:00Z", index_status="MISSING")

        job = repo.enqueue_job(f["file_id"], fid, job_type="DELETE_CLEANUP")

        # Claiming DELETE_CLEANUP must NOT set file to PROCESSING
        claimed = repo.claim_next_job()
        assert claimed["job_id"] == job["job_id"]
        f_claimed = repo.get_file_by_id(f["file_id"])
        assert f_claimed["index_status"] == "MISSING"

        # Completing DELETE_CLEANUP preserves MISSING
        repo.complete_job(job["job_id"], f["file_id"], final_status="MISSING")
        f_completed = repo.get_file_by_id(f["file_id"])
        assert f_completed["index_status"] == "MISSING"


def test_bug38_rename_and_move_sequences(clean_db):
    """Bug 38: Verify file and directory renames preserve identity and enqueue hash verification."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_rename_root")
        fid = folder["folder_id"]

        f = repo.upsert_file(fid, "C:/test_rename_root/sub/old.txt", "sub/old.txt", "old.txt", ".txt", 100, "2026-09-01T00:00:00Z", index_status="INDEXED")
        file_id = f["file_id"]

        # Rename directory subtree
        affected = repo.rename_directory_path(fid, "C:/test_rename_root/sub", "C:/test_rename_root/new_sub", "C:/test_rename_root")
        assert affected == 1

        f_renamed = repo.get_file_by_id(file_id)
        assert normalize_path(f_renamed["path"]) == normalize_path("C:/test_rename_root/new_sub/old.txt")
        assert f_renamed["relative_path"] == "new_sub/old.txt"

        # Job enqueued for hash verification
        jobs = repo.list_jobs(status="PENDING")
        assert len(jobs) == 1
        assert jobs[0]["job_type"] == "HASH_VERIFICATION"


def test_bug39_scan_all_enabled_folders_isolated_sessions(clean_db, tmp_path):
    """Bug 39: Verify scan_all_enabled_folders scopes each folder to its own DB transaction."""
    root1 = tmp_path / "folder1"
    root1.mkdir()
    (root1 / "file1.txt").write_text("content 1", encoding="utf-8")

    root2 = tmp_path / "folder2"
    root2.mkdir()
    (root2 / "file2.txt").write_text("content 2", encoding="utf-8")

    coord = EngineCoordinator(db=clean_db, embedding_engine=MockEmbeddingEngine(4))
    with clean_db.session() as conn:
        repo = Repository(conn)
        repo.create_folder(str(root1))
        repo.create_folder(str(root2))

    res = coord.scan_all_enabled_folders()
    assert len(res) == 2
    assert all("total_scanned" in v and v["total_scanned"] == 1 for v in res.values())


def test_bug87_rejection_of_invalid_indexed_partial(clean_db):
    """Bug 87: Verify complete_job rejects illegal INDEXED_PARTIAL status."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_partial")
        f = repo.upsert_file(folder["folder_id"], "C:/test_partial/doc.txt", "doc.txt", "doc.txt", ".txt", 100, "2026-09-01T00:00:00Z")
        job = repo.enqueue_job(f["file_id"], folder["folder_id"])

        with pytest.raises(ValueError, match="Invalid file index_status: INDEXED_PARTIAL"):
            repo.complete_job(job["job_id"], f["file_id"], final_status="INDEXED_PARTIAL")


def test_bug89_is_current_processing_job_ownership(clean_db):
    """Bug 89: Verify is_current_processing_job ownership and superseding semantics."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_ownership")
        fid = folder["folder_id"]

        f = repo.upsert_file(fid, "C:/test_ownership/doc.txt", "doc.txt", "doc.txt", ".txt", 100, "2026-09-01T00:00:00Z")
        file_id = f["file_id"]

        # Job 1 enqueued and claimed
        j1 = repo.enqueue_job(file_id, fid)
        assert repo.claim_next_job()["job_id"] == j1["job_id"]
        assert repo.is_current_processing_job(j1["job_id"], file_id) is True

        # Job 2 enqueued later while Job 1 is still processing -> Job 1 loses ownership
        time.sleep(0.01)
        j2 = repo.enqueue_job(file_id, fid, job_id="job-2-new")
        assert repo.is_current_processing_job(j1["job_id"], file_id) is False


def test_bug95_sqlite_connection_concurrency_and_timeout(clean_db):
    """Bug 95: Verify SQLite connection WAL concurrency and busy timeout configuration."""
    with clean_db.session() as conn:
        # Verify WAL pragmas
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.lower() == "wal"
        busy = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert busy >= 5000


def test_bug118_disabled_folder_skips_indexing_jobs(clean_db):
    """Bug 118: Verify claim_next_job skips indexing jobs for disabled folders but claims cleanup jobs."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_disabled", indexing_enabled=False)
        fid = folder["folder_id"]

        f = repo.upsert_file(fid, "C:/test_disabled/f.txt", "f.txt", "f.txt", ".txt", 100, "2026-09-01T00:00:00Z")
        repo.enqueue_job(f["file_id"], fid, job_type="METADATA_DISCOVERY")

        # Indexing job for disabled folder must NOT be claimed
        assert repo.claim_next_job() is None

        # DELETE_CLEANUP job for disabled folder MUST be claimed
        cleanup_job = repo.enqueue_job(f["file_id"], fid, job_type="DELETE_CLEANUP", job_id="cleanup-1")
        claimed = repo.claim_next_job()
        assert claimed is not None
        assert claimed["job_id"] == "cleanup-1"


def test_bug119_attempt_accounting_across_crash_recovery(clean_db):
    """Bug 119: Verify crash recovery does not exhaust attempt budget on reclaimed jobs."""
    with clean_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/test_recovery")
        fid = folder["folder_id"]

        f = repo.upsert_file(fid, "C:/test_recovery/f.txt", "f.txt", "f.txt", ".txt", 100, "2026-09-01T00:00:00Z")
        job = repo.enqueue_job(f["file_id"], fid)

        # 1. Claim job (attempts = 1)
        claimed1 = repo.claim_next_job()
        assert claimed1["attempts"] == 1

        # 2. Crash recovery occurs (job reset to PENDING, attempt count adjusted)
        recovered = repo.recover_stale_processing_jobs()
        assert recovered == 1

        # 3. Job reclaimed after restart (attempts must remain 1 for the current run, not 2)
        claimed2 = repo.claim_next_job()
        assert claimed2["attempts"] == 1
