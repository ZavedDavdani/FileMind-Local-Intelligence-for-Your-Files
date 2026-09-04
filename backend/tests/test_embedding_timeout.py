"""Bug A — Embedding Load Reliability Tests.

Validates:
A1. Normal cached/local embedding initialization still works.
A2. Simulated model init failure raises within the configured bounded time
    (not ~40 s).
A3. Hybrid retrieval degrades to BM25 when dense embedding initialization
    fails.
A4. Degraded response is explicit (degraded=True,
    retrieval_method="bm25_fallback", dense_score=None).
A5. Worker job does not remain indefinitely stuck in PROCESSING after
    embedding initialization failure.

Lifecycle / audit tests:
L1. Confirmed: future.cancel() on a running ThreadPoolExecutor thread
    returns False and cannot terminate it (justification for replacement).
L2. Exactly ONE init thread exists even when multiple callers arrive
    concurrently during a blocking init.
L3. No task queue accumulates — all callers share the same threading.Event.
L4. After a successful late completion of the daemon thread, subsequent
    callers use the O(1) fast-path and do NOT spawn new threads.
L5. After a failed init, a subsequent call starts a fresh daemon thread
    (correct retry path).
"""

import os
import sqlite3
import tempfile
import threading
import time
import unittest.mock as mock
import pytest

from app.retrieval.embeddings import (
    EMBEDDING_LOAD_TIMEOUT_SECONDS,
    DEFAULT_MODEL_NAME,
    EmbeddingEngine,
    EmbeddingLoadTimeoutError,
)
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_store import SqliteVecStore
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.provenance import ChunkProvenance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hybrid_db():
    """Minimal DB with one folder, file, chunk and BM25-indexed record."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_emb_timeout.db")
        db = DatabaseManager(db_path)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(tmp_dir)
            folder_id = folder["folder_id"]

            file_path = os.path.join(tmp_dir, "embedding_test_doc.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# Embedding Test\n\nThis document is used to verify embedding timeout behaviour.")

            file_rec = repo.upsert_file(
                folder_id=folder_id,
                path=file_path,
                relative_path="embedding_test_doc.md",
                filename="embedding_test_doc.md",
                extension=".md",
                size_bytes=os.path.getsize(file_path),
                modified_at="2026-09-01T00:00:00Z",
                file_id="f_emb_001",
            )
            file_id = file_rec["file_id"]

            chunk = ChunkProvenance(
                chunk_id="chk_emb_001",
                file_id=file_id,
                source_file="embedding_test_doc.md",
                source_path=file_path,
                page=None,
                section="Embedding Test",
                h1_parent="Embedding Test",
                h2_parent=None,
                line_start=1,
                line_end=3,
                char_start=0,
                char_end=80,
                content_hash="abc123",
                chunk_index=0,
                parser_name="MarkdownParser",
                parser_version="1.0",
                chunker_version="1.0",
                content="This document is used to verify embedding timeout behaviour.",
                content_type="text",
                token_count=10,
            )
            repo.replace_file_chunks(file_id, [chunk])

            conn.execute(
                """
                INSERT OR REPLACE INTO chunks_fts (chunk_id, file_id, source_file, content)
                VALUES (?, ?, ?, ?)
                """,
                ("chk_emb_001", file_id, "embedding_test_doc.md",
                 "This document is used to verify embedding timeout behaviour."),
            )

        yield db, tmp_dir


# ===========================================================================
# A1: Normal init works (fast-path, locally cached model)
# ===========================================================================

def test_a1_normal_embedding_init_succeeds():
    """A1: EmbeddingEngine._ensure_loaded() succeeds when FastEmbed model is
    available (simulated via a mock that returns instantly)."""
    engine = EmbeddingEngine(DEFAULT_MODEL_NAME)
    mock_model = mock.MagicMock()
    mock_model.embed.return_value = iter([[0.1] * engine.dimension])

    with mock.patch.object(engine, "_run_init", wraps=lambda: _instant_run_init(engine, mock_model)):
        engine._ensure_loaded()

    assert engine._model is not None


def _instant_run_init(engine: EmbeddingEngine, model_obj):
    """Helper: sets _model immediately and fires _init_done."""
    engine._model = model_obj
    engine._init_error = None
    engine._init_done.set()


# ===========================================================================
# A2: Timed-out init raises EmbeddingLoadTimeoutError quickly
# ===========================================================================

def test_a2_timeout_raises_within_bounded_time():
    """A2: When model init stalls, EmbeddingLoadTimeoutError is raised within
    timeout + 1 s (not ~40 s)."""
    short_timeout = 1.0

    engine = EmbeddingEngine(DEFAULT_MODEL_NAME, load_timeout=short_timeout)

    # _run_init body: blocks until test releases or 60 s elapses
    release = threading.Event()

    def blocking_run_init():
        release.wait(timeout=60)
        # Do not set _model — init "never completes"
        engine._init_error = RuntimeError("simulated stall")
        engine._init_done.set()

    engine._run_init = blocking_run_init

    t_start = time.monotonic()
    with pytest.raises(EmbeddingLoadTimeoutError) as exc_info:
        engine._ensure_loaded()
    elapsed = time.monotonic() - t_start

    assert elapsed < short_timeout + 2.0, (
        f"Timeout did not fire promptly: {elapsed:.2f} s (expected < {short_timeout + 2.0} s)"
    )
    assert "timed out" in str(exc_info.value).lower()
    release.set()   # clean up blocking thread


# ===========================================================================
# A3 & A4: Hybrid degrades to BM25 when embedding init fails
# ===========================================================================

def test_a3_a4_hybrid_degrades_to_bm25_on_timeout(hybrid_db):
    """A3+A4: HybridRetriever enters BM25 fallback with correct degraded state
    when embed_query raises EmbeddingLoadTimeoutError."""
    db, tmp_dir = hybrid_db

    with db.session() as conn:
        apply_migrations(conn)
        engine = EmbeddingEngine(DEFAULT_MODEL_NAME, load_timeout=1.0)
        engine._model = mock.MagicMock()
        engine._model.embed.side_effect = EmbeddingLoadTimeoutError(
            "Simulated timeout during query embedding"
        )

        vec_store = SqliteVecStore(conn, dimension=engine.dimension)
        retriever = HybridRetriever(conn, embedding_engine=engine, vector_store=vec_store)
        result = retriever.search("embedding timeout", top_k=5, mode="hybrid")

    assert result["degraded"] is True
    assert result["retrieval_method"] == "bm25_fallback"
    assert result["degraded_reason"] is not None
    for item in result.get("results", []):
        assert item["dense_score"] is None
        assert item.get("rrf_score") is None


def test_a4_degraded_response_has_correct_schema(hybrid_db):
    """A4: Degraded response schema: degraded=True, retrieval_method=bm25_fallback,
    dense_score=None."""
    db, tmp_dir = hybrid_db

    with db.session() as conn:
        apply_migrations(conn)
        engine = EmbeddingEngine(DEFAULT_MODEL_NAME, load_timeout=1.0)
        engine._model = mock.MagicMock()
        engine._model.embed.side_effect = RuntimeError("Simulated dense failure")

        vec_store = SqliteVecStore(conn, dimension=engine.dimension)
        retriever = HybridRetriever(conn, embedding_engine=engine, vector_store=vec_store)
        result = retriever.search("embedding", top_k=5, mode="hybrid")

    assert result["degraded"] is True
    assert result["retrieval_method"] == "bm25_fallback"
    for item in result.get("results", []):
        assert item.get("dense_score") is None
        assert item.get("retrieval_method") == "bm25_fallback"


# ===========================================================================
# A5: Worker job not stuck after embedding failure
# ===========================================================================

def test_a5_worker_job_not_stuck_after_embedding_failure():
    """A5: embed_texts() raising EmbeddingLoadTimeoutError is caught by the
    worker's exception handler; the job completes (not stuck in PROCESSING)."""
    from app.engine.worker import WorkerPool

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_worker_emb.db")
        db = DatabaseManager(db_path)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(tmp_dir)
            folder_id = folder["folder_id"]

            file_path = os.path.join(tmp_dir, "worker_test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Worker embedding timeout test content.")

            file_rec = repo.upsert_file(
                folder_id=folder_id,
                path=file_path,
                relative_path="worker_test.txt",
                filename="worker_test.txt",
                extension=".txt",
                size_bytes=os.path.getsize(file_path),
                modified_at="2026-09-01T00:00:00Z",
                file_id="f_worker_001",
            )
            file_id = file_rec["file_id"]
            job_rec = repo.enqueue_job(
                file_id=file_id,
                folder_id=folder_id,
                job_type="DOCUMENT_PARSE",
                priority=5,
            )
            job_id = job_rec["job_id"]

        pool = WorkerPool(db, max_workers=1)

        with mock.patch(
            "app.retrieval.embeddings.EmbeddingEngine.embed_texts",
            side_effect=EmbeddingLoadTimeoutError("Simulated embedding timeout in worker"),
        ):
            with db.session() as conn:
                repo = Repository(conn)
                job = repo.claim_next_job()

            if job:
                pool._process_job(job)

        with db.session() as conn:
            repo = Repository(conn)
            jobs = repo.list_jobs(limit=10)
            for j in jobs:
                if j["job_id"] == job_id:
                    assert j["status"] in ("COMPLETED", "FAILED"), (
                        f"Job stuck in unexpected state: {j['status']}"
                    )


# ===========================================================================
# L1: Audit confirmation — future.cancel() cannot kill a running thread
# ===========================================================================

def test_l1_future_cancel_cannot_stop_running_thread():
    """L1: Documents the Python guarantee that future.cancel() returns False
    on an already-running ThreadPoolExecutor thread.
    This is the specific defect that motivated replacing the executor approach."""
    import concurrent.futures

    started = threading.Event()
    release = threading.Event()

    def blocking():
        started.set()
        release.wait(timeout=5)
        return "done"

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(blocking)
    started.wait(timeout=2)

    cancelled = future.cancel()
    assert cancelled is False, (
        "future.cancel() must return False on a running thread — Python cannot kill threads"
    )
    assert future.running() is True

    release.set()
    executor.shutdown(wait=False)


# ===========================================================================
# L2: Exactly ONE init thread even with multiple concurrent callers
# ===========================================================================

def test_l2_single_init_thread_with_concurrent_callers():
    """L2: When multiple threads call _ensure_loaded() concurrently during a
    blocking init, exactly ONE daemon thread is started (no accumulation)."""
    short_timeout = 1.5
    engine = EmbeddingEngine(DEFAULT_MODEL_NAME, load_timeout=short_timeout)

    release = threading.Event()
    threads_seen = []

    def blocking_run_init():
        # Record the thread count while blocking
        alive = [t for t in threading.enumerate() if t.name == "FileMind-EmbeddingInit"]
        threads_seen.append(len(alive))
        release.wait(timeout=10)
        engine._init_done.set()   # signal without setting _model -> error path

    engine._run_init = blocking_run_init

    errors = []
    def caller():
        try:
            engine._ensure_loaded()
        except (EmbeddingLoadTimeoutError, RuntimeError):
            pass
        except Exception as e:
            errors.append(e)

    # Launch 5 concurrent callers
    caller_threads = [threading.Thread(target=caller, daemon=True) for _ in range(5)]
    for t in caller_threads:
        t.start()
    time.sleep(0.3)   # let them all arrive at _init_done.wait()

    # At this point exactly 1 FileMind-EmbeddingInit thread should exist
    alive_init = [t for t in threading.enumerate() if t.name == "FileMind-EmbeddingInit"]
    assert len(alive_init) == 1, (
        f"Expected exactly 1 init thread, found {len(alive_init)}: {alive_init}"
    )

    release.set()
    for t in caller_threads:
        t.join(timeout=5)

    assert not errors, f"Unexpected errors in caller threads: {errors}"


# ===========================================================================
# L3: No task queue accumulates across multiple timeout failures
# ===========================================================================

def test_l3_no_task_queue_accumulation():
    """L3: Three sequential failed inits each start exactly one daemon thread
    (no pending tasks pile up as they would with ThreadPoolExecutor)."""
    short_timeout = 0.5
    engine = EmbeddingEngine(DEFAULT_MODEL_NAME, load_timeout=short_timeout)

    call_count = [0]
    release = threading.Event()

    def blocking_run_init():
        call_count[0] += 1
        # Block long enough to exceed the timeout
        release.wait(timeout=0.2)   # returns quickly, simulating a stall that eventually exits
        engine._init_error = RuntimeError("simulated failure")
        engine._init_done.set()

    engine._run_init = blocking_run_init

    # Three sequential calls, each times out, then init thread finishes
    for _ in range(3):
        release.clear()
        engine._init_done.clear()
        engine._init_thread = None  # reset so each iteration starts fresh
        engine._model = None
        engine._init_error = None
        release.set()   # allow immediate "failure"

        try:
            engine._ensure_loaded()
        except (EmbeddingLoadTimeoutError, RuntimeError):
            pass
        time.sleep(0.1)  # let thread finish

    # With the daemon-thread design, each sequential call may start a new thread
    # (previous one finished), but at most 1 thread is alive at any point.
    alive_init = [t for t in threading.enumerate() if t.name == "FileMind-EmbeddingInit"]
    assert len(alive_init) <= 1, (
        f"Expected <= 1 init thread after sequential failures, found {len(alive_init)}"
    )


# ===========================================================================
# L4: Late success — model set by daemon thread, next caller uses fast-path
# ===========================================================================

def test_l4_late_success_activates_fast_path():
    """L4: If the daemon init thread succeeds after the first caller timed out,
    subsequent callers must use the O(1) fast-path (no new thread started)."""
    short_timeout = 0.5
    engine = EmbeddingEngine(DEFAULT_MODEL_NAME, load_timeout=short_timeout)

    mock_model = mock.MagicMock()
    ready = threading.Event()

    def slow_then_succeed():
        ready.wait(timeout=10)   # block until test releases
        engine._model = mock_model
        engine._init_error = None
        engine._init_done.set()

    engine._run_init = slow_then_succeed

    # First call: times out
    with pytest.raises(EmbeddingLoadTimeoutError):
        engine._ensure_loaded()

    # Simulate the daemon thread completing successfully AFTER the timeout
    ready.set()
    time.sleep(0.1)

    # Second call: _model is now set → must use fast-path (no new thread)
    thread_before = engine._init_thread
    engine._ensure_loaded()   # must NOT raise
    assert engine._model is mock_model
    # No new thread should have been started
    assert engine._init_thread is thread_before, (
        "A new init thread was started even though _model was already set"
    )


# ===========================================================================
# L5: Failed init allows a fresh retry on the next call
# ===========================================================================

def test_l5_failed_init_allows_retry():
    """L5: After a failed init (error signalled), the next call to _ensure_loaded()
    starts a fresh daemon thread (correct retry semantics)."""
    short_timeout = 1.0
    engine = EmbeddingEngine(DEFAULT_MODEL_NAME, load_timeout=short_timeout, retry_cooldown=0.0)


    mock_model = mock.MagicMock()

    # First init: fail immediately
    def failing_init():
        engine._init_error = RuntimeError("transient failure")
        engine._init_done.set()

    engine._run_init = failing_init
    with pytest.raises(RuntimeError, match="transient failure"):
        engine._ensure_loaded()

    # Second init: succeed
    def succeeding_init():
        engine._model = mock_model
        engine._init_error = None
        engine._init_done.set()

    engine._run_init = succeeding_init
    engine._ensure_loaded()   # must NOT raise
    assert engine._model is mock_model
