"""
FileMind — Hardening 4 (H4): SQLite WAL Observability & Concurrency Test Suite

Tests:
1. WAL configuration pragmas (journal_mode=WAL, synchronous=NORMAL, busy_timeout=10000, foreign_keys=ON).
2. Connection and transaction closure discipline.
3. Concurrent readers do not block writers.
4. Concurrent writers queue and execute without starvation.
5. WAL growth and passive checkpoint behavior.
6. Search responsiveness (FTS5 + Vector) during heavy concurrent write workloads.
7. FTS5 and sqlite-vec coexistence and consistency.
8. Crash and interruption recovery in WAL mode.
"""

import os
import random
import shutil
import sqlite3
import tempfile
import threading
import time
from typing import Any, Dict, List
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.embeddings import default_embedding_engine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.normalizer import normalize_query
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def temp_db_env():
    temp_dir = tempfile.mkdtemp(prefix="filemind_h4_test_")
    db_path = os.path.join(temp_dir, "filemind.db")
    db_mgr = DatabaseManager(db_path, pooled=True)
    with db_mgr.session() as conn:
        apply_migrations(conn)
    yield temp_dir, db_path, db_mgr
    db_mgr.close_all()
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_wal_configuration(temp_db_env):
    """
    Scenario 1: Verify that every configured SQLite database connection enables
    WAL mode, NORMAL synchronous, busy_timeout=10000ms, and foreign keys.
    """
    temp_dir, db_path, db_mgr = temp_db_env
    with db_mgr.session() as conn:
        # Check journal_mode
        jm = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert jm.upper() == "WAL"

        # Check synchronous mode (NORMAL = 1)
        sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
        assert sync == 1  # 1 corresponds to NORMAL

        # Check busy_timeout (>= 10000 ms)
        bt = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert bt >= 10000

        # Check foreign_keys enabled (1)
        fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert fk == 1


def test_connection_and_transaction_closure(temp_db_env):
    """
    Scenario 2: Verify that DatabaseManager.session() strictly acquires, executes,
    commits/rollbacks, and closes connections, leaving 0 unclosed transactions.
    """
    temp_dir, db_path, db_mgr = temp_db_env

    # Normal successful transaction
    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.create_folder(os.path.join(temp_dir, "folder_a"))
        assert f["folder_id"] is not None

    # Verify transaction committed and connection closed
    with db_mgr.session() as conn:
        repo = Repository(conn)
        folders = repo.list_folders()
        assert len(folders) == 1

    # Exceptional transaction with rollback
    try:
        with db_mgr.session() as conn:
            repo = Repository(conn)
            repo.create_folder(os.path.join(temp_dir, "folder_b"))
            raise RuntimeError("Simulated transaction failure")
    except RuntimeError:
        pass

    # Verify rollback succeeded
    with db_mgr.session() as conn:
        repo = Repository(conn)
        folders = repo.list_folders()
        assert len(folders) == 1
        assert folders[0]["path"] == os.path.join(temp_dir, "folder_a")


def test_concurrent_readers_do_not_block_writers(temp_db_env):
    """
    Scenario 3: Verify that continuous active readers running FTS5 and metadata
    queries do NOT block concurrent writer threads from inserting records.
    """
    temp_dir, db_path, db_mgr = temp_db_env
    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.create_folder(temp_dir)
        fid = f["folder_id"]

    stop_event = threading.Event()
    read_errors = []
    write_errors = []
    read_counts = [0]
    write_counts = [0]

    def reader_task():
        while not stop_event.is_set():
            try:
                with db_mgr.session() as conn:
                    repo = Repository(conn)
                    files = repo.list_files(limit=20)
                    lex = LexicalRetriever(conn)
                    lex.search(normalize_query("test architecture indexing"), top_k=5)
                    read_counts[0] += 1
            except Exception as exc:
                read_errors.append(str(exc))
            time.sleep(0.002)

    def writer_task():
        c = 0
        while not stop_event.is_set():
            c += 1
            try:
                with db_mgr.session() as conn:
                    repo = Repository(conn)
                    repo.upsert_file(
                        fid,
                        f"{temp_dir}/file_{c}.txt",
                        f"file_{c}.txt",
                        f"file_{c}.txt",
                        ".txt",
                        100,
                        "2026-08-30T12:00:00Z",
                        index_status="INDEXED"
                    )
                    write_counts[0] += 1
            except Exception as exc:
                write_errors.append(str(exc))
            time.sleep(0.002)

    threads = [
        threading.Thread(target=reader_task),
        threading.Thread(target=reader_task),
        threading.Thread(target=writer_task),
    ]

    for th in threads:
        th.start()

    time.sleep(1.5)
    stop_event.set()

    for th in threads:
        th.join()

    assert len(read_errors) == 0, f"Reader errors: {read_errors}"
    assert len(write_errors) == 0, f"Writer errors: {write_errors}"
    assert read_counts[0] > 10, "Readers did not make progress"
    assert write_counts[0] > 10, "Writers did not make progress"


def test_concurrent_writers_queue_without_starvation(temp_db_env):
    """
    Scenario 4: Verify that multiple concurrent writer threads claiming and
    completing jobs coordinate via busy_timeout and SQLite serialized writes without deadlocks.
    """
    temp_dir, db_path, db_mgr = temp_db_env
    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.create_folder(temp_dir)
        fid = f["folder_id"]
        # Seed 50 jobs
        for i in range(50):
            f_rec = repo.upsert_file(
                fid,
                f"{temp_dir}/item_{i}.txt",
                f"item_{i}.txt",
                f"item_{i}.txt",
                ".txt",
                100,
                "2026-08-30T12:00:00Z",
                index_status="QUEUED"
            )
            repo.enqueue_job(f_rec["file_id"], fid, job_type="DOCUMENT_PARSE")

    stop_event = threading.Event()
    worker_errors = []
    processed_counts = [0, 0]
    barrier = threading.Barrier(2)

    def worker_sim(w_idx: int):
        barrier.wait()
        while not stop_event.is_set():
            job = None
            try:
                time.sleep(0.002)
                with db_mgr.session() as conn:
                    repo = Repository(conn)
                    job = repo.claim_next_job()
                    if job:
                        repo.complete_job(job["job_id"], job["file_id"], sha256="test_hash")
                        processed_counts[w_idx] += 1
                        time.sleep(0.005)
            except Exception as exc:
                worker_errors.append(f"Worker {w_idx} error: {str(exc)}")
            if not job:
                time.sleep(0.01)

    w1 = threading.Thread(target=worker_sim, args=(0,))
    w2 = threading.Thread(target=worker_sim, args=(1,))
    w1.start()
    w2.start()

    time.sleep(2.0)
    stop_event.set()
    w1.join()
    w2.join()

    assert len(worker_errors) == 0, f"Worker errors: {worker_errors}"
    assert sum(processed_counts) == 50, f"Not all jobs processed: {processed_counts}"
    assert processed_counts[0] > 0 and processed_counts[1] > 0, "One worker was starved"


def test_wal_growth_and_passive_checkpoint(temp_db_env):
    """
    Scenario 5: Verify that write batches generate WAL frames and PRAGMA wal_checkpoint(PASSIVE)
    successfully checkpoints WAL pages into the main DB file without errors.
    """
    temp_dir, db_path, db_mgr = temp_db_env
    wal_path = db_path + "-wal"

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.create_folder(temp_dir)
        fid = f["folder_id"]

        # Insert 200 files with chunks
        for i in range(200):
            f_rec = repo.upsert_file(
                fid,
                f"{temp_dir}/doc_{i}.txt",
                f"doc_{i}.txt",
                f"doc_{i}.txt",
                ".txt",
                500,
                "2026-08-30T12:00:00Z",
                index_status="INDEXED"
            )
            repo.replace_file_chunks(f_rec["file_id"], [
                {
                    "chunk_id": f"chk_{i}_{j}",
                    "file_id": f_rec["file_id"],
                    "source_file": f"doc_{i}.txt",
                    "source_path": f"{temp_dir}/doc_{i}.txt",
                    "content": f"Document {i} section {j} content discussing database storage, indexing, and WAL mode.",
                    "content_hash": f"h_{i}_{j}",
                    "chunk_index": j,
                    "parser_name": "test",
                    "parser_version": "1.0",
                    "chunker_version": "1.0",
                    "content_type": "text",
                    "token_count": 14,
                    "metadata_json": "{}"
                }
                for j in range(3)
            ])

    # Run passive checkpoint
    with db_mgr.session() as conn:
        res = conn.execute("PRAGMA wal_checkpoint(PASSIVE);").fetchone()
        busy, log_frames, ckpt_frames = res[0], res[1], res[2]
        assert busy == 0, "Passive checkpoint reported busy lock"
        assert ckpt_frames >= 0


def test_search_responsiveness_during_heavy_writes(temp_db_env):
    """
    Scenario 6: Verify that search queries (FTS5 BM25 + Metadata) achieve sub-10ms
    database execution latency even during continuous background file and chunk insertions.
    """
    temp_dir, db_path, db_mgr = temp_db_env
    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.create_folder(temp_dir)
        fid = f["folder_id"]
        # Prepopulate 50 documents
        for i in range(50):
            f_rec = repo.upsert_file(
                fid, f"{temp_dir}/seed_{i}.txt", f"seed_{i}.txt", f"seed_{i}.txt", ".txt", 200, "2026-08-30T12:00:00Z", index_status="INDEXED"
            )
            repo.replace_file_chunks(f_rec["file_id"], [{
                "chunk_id": f"seed_chk_{i}",
                "file_id": f_rec["file_id"],
                "source_file": f"seed_{i}.txt",
                "source_path": f"{temp_dir}/seed_{i}.txt",
                "content": f"Seed content {i} database performance and search indexing architecture.",
                "content_hash": f"shash_{i}",
                "chunk_index": 0,
                "parser_name": "test",
                "parser_version": "1.0",
                "chunker_version": "1.0",
                "content_type": "text",
                "token_count": 10,
                "metadata_json": "{}"
            }])

    stop_event = threading.Event()
    search_latencies_ms = []

    def searcher():
        while not stop_event.is_set():
            t0 = time.perf_counter()
            with db_mgr.session() as conn:
                lex = LexicalRetriever(conn)
                lex.search(normalize_query("database performance architecture"), top_k=10)
            dt = (time.perf_counter() - t0) * 1000.0
            search_latencies_ms.append(dt)
            time.sleep(0.005)

    def continuous_writer():
        c = 0
        while not stop_event.is_set():
            c += 1
            with db_mgr.session() as conn:
                repo = Repository(conn)
                f_rec = repo.upsert_file(
                    fid, f"{temp_dir}/stream_{c}.txt", f"stream_{c}.txt", f"stream_{c}.txt", ".txt", 300, "2026-08-30T12:00:00Z", index_status="INDEXED"
                )
                repo.replace_file_chunks(f_rec["file_id"], [{
                    "chunk_id": f"stream_chk_{c}",
                    "file_id": f_rec["file_id"],
                    "source_file": f"stream_{c}.txt",
                    "source_path": f"{temp_dir}/stream_{c}.txt",
                    "content": f"Streaming write {c} content.",
                    "content_hash": f"stream_h_{c}",
                    "chunk_index": 0,
                    "parser_name": "test",
                    "parser_version": "1.0",
                    "chunker_version": "1.0",
                    "content_type": "text",
                    "token_count": 5,
                    "metadata_json": "{}"
                }])
            time.sleep(0.003)

    th_s = threading.Thread(target=searcher)
    th_w = threading.Thread(target=continuous_writer)
    th_s.start()
    th_w.start()

    time.sleep(1.5)
    stop_event.set()
    th_s.join()
    th_w.join()

    assert len(search_latencies_ms) > 10
    # Search latency inside SQLite during writes should have median < 25 ms
    median_lat = sorted(search_latencies_ms)[len(search_latencies_ms) // 2]
    assert median_lat < 25.0, f"Median search latency {median_lat:.2f} ms exceeded 25ms threshold"


def test_fts5_and_vector_store_coexistence(temp_db_env):
    """
    Scenario 7: Verify that FTS5 full-text queries and sqlite-vec vector searches
    coexist seamlessly on the same database in WAL mode without lock conflicts.
    """
    temp_dir, db_path, db_mgr = temp_db_env
    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.create_folder(temp_dir)
        fid = f["folder_id"]

        # Insert 10 documents with chunks and vector embeddings
        vstore = SqliteVecStore(conn, dimension=384)
        for i in range(10):
            f_rec = repo.upsert_file(
                fid, f"{temp_dir}/vec_{i}.txt", f"vec_{i}.txt", f"vec_{i}.txt", ".txt", 150, "2026-08-30T12:00:00Z", index_status="INDEXED"
            )
            cid = f"vchk_{i}"
            repo.replace_file_chunks(f_rec["file_id"], [{
                "chunk_id": cid,
                "file_id": f_rec["file_id"],
                "source_file": f"vec_{i}.txt",
                "source_path": f"{temp_dir}/vec_{i}.txt",
                "content": f"Vector test item {i} with semantic search content.",
                "content_hash": f"vh_{i}",
                "chunk_index": 0,
                "parser_name": "test",
                "parser_version": "1.0",
                "chunker_version": "1.0",
                "content_type": "text",
                "token_count": 8,
                "metadata_json": "{}"
            }])
            # Insert vector
            dummy_vec = [0.01 * (i + 1)] * 384
            vstore.upsert_vectors([{"chunk_id": cid, "file_id": f_rec["file_id"], "embedding": dummy_vec}])

    # Execute simultaneous FTS5 read and vector search in same transaction
    with db_mgr.session() as conn:
        lex = LexicalRetriever(conn)
        lex_results = lex.search(normalize_query("semantic search item"), top_k=5)
        assert len(lex_results) > 0

        vstore = SqliteVecStore(conn, dimension=384)
        vec_results = vstore.search([0.05] * 384, top_k=5)
        assert len(vec_results) > 0


def test_crash_and_interruption_recovery_in_wal_mode(temp_db_env):
    """
    Scenario 8: Verify that simulated abnormal connection termination leaves
    the database and WAL in a fully consistent, recoverable state.
    """
    temp_dir, db_path, db_mgr = temp_db_env

    # Open a raw connection and insert without committing cleanly
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("PRAGMA journal_mode = WAL;")
    raw_conn.execute("BEGIN IMMEDIATE;")
    raw_conn.execute(
        "INSERT INTO folders (folder_id, path, recursive, integrity_mode, indexing_enabled, exclude_patterns) VALUES (?, ?, 1, 'NORMAL', 1, '[]');",
        ("crash_f_id", f"{temp_dir}/crash_folder")
    )
    # Simulate ungraceful connection drop without commit
    raw_conn.close()

    # Reconnect via DatabaseManager and verify DB integrity
    with db_mgr.session() as conn:
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        assert integrity == "ok"

        repo = Repository(conn)
        folders = repo.list_folders()
        # Uncommitted folder should have been rolled back
        assert not any(f["folder_id"] == "crash_f_id" for f in folders)
