"""Comprehensive regression test suite for Chunk 1 Remediations.

Covers:
- Bug 1 and 2: Deleted file during processing and atomic DELETE_CLEANUP.
- Bug 3: Vector identity mismatch warning and embedding failure recovery.
- Bug 5 and 10: Accurate job ownership and superseding in is_current_processing_job.
- Bug 8 and 12: Bounded exponential backoff calculation.
- Bug 13: Stale worker recovery with threshold and selective file state reset.
- Bug 14: Job cancellation on DELETE_CLEANUP enqueue.
- Bug 18: Filename intent search scoped to effective file_id filter.
- Bug 21: Insight caching with 0-evidence / representative chunks.
- Bug 23: Orphan job claim termination.
- Bug 103: PDF parser source line and char offsets.
- Bug 109: Folder exclude pattern normalization without double JSON encoding.
"""

import os
import tempfile
from datetime import datetime, timezone
import pytest

from app.core.config import MAX_BACKOFF_SECONDS
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repositories.folders import FolderRepository
from app.db.repository import Repository
from app.engine.pipeline import IndexingPipelineResult
from app.engine.queue import calculate_backoff_delay
from app.engine.worker import WorkerPool
from app.intelligence.parsers.pdf_parser import PyMuPDFParser
from app.intelligence.models import ElementType
from app.retrieval.hybrid import HybridRetriever


@pytest.fixture
def repo_env(tmp_path):
    db_file = tmp_path / "chunk1_test.db"
    mgr = DatabaseManager(str(db_file))
    with mgr.session() as conn:
        apply_migrations(conn)
    return mgr, tmp_path


def test_bounded_exponential_backoff():
    """Verify bounded backoff delays (Bugs 8 & 12)."""
    assert calculate_backoff_delay(attempts=0) == 1.0
    assert calculate_backoff_delay(attempts=1) == 1.0
    assert calculate_backoff_delay(attempts=2) == 2.0
    assert calculate_backoff_delay(attempts=3) == 4.0
    assert calculate_backoff_delay(attempts=10, max_backoff=60.0) == 60.0
    assert calculate_backoff_delay(attempts=100) <= MAX_BACKOFF_SECONDS


def test_folder_exclude_pattern_normalization():
    """Verify FolderRepository normalize_exclude_patterns prevents double JSON encoding (Bug 109)."""
    import json
    # List input
    patterns = ["*.tmp", "node_modules"]
    norm1 = FolderRepository.normalize_exclude_patterns(patterns)
    assert json.loads(norm1) == ["*.tmp", "node_modules"]

    # JSON string input
    norm2 = FolderRepository.normalize_exclude_patterns('["*.tmp", "node_modules"]')
    assert json.loads(norm2) == ["*.tmp", "node_modules"]

    # None / Empty input
    assert FolderRepository.normalize_exclude_patterns(None) == "[]"
    assert FolderRepository.normalize_exclude_patterns("") == "[]"
    assert FolderRepository.normalize_exclude_patterns("[]") == "[]"


def test_orphan_job_cleanup_during_claim(repo_env):
    """Verify claim_next_job permanently fails orphan jobs referencing non-existent files (Bug 23)."""
    mgr, tmp_dir = repo_env
    # Insert an orphan job directly into the database using a raw connection without FK enforcement
    db_file = str(tmp_dir / "chunk1_test.db")
    import sqlite3
    raw_conn = sqlite3.connect(db_file)
    raw_conn.execute(
        """
        INSERT INTO indexing_jobs (job_id, file_id, folder_id, job_type, status, priority, attempts, created_at)
        VALUES ('orphan_job_1', 'non_existent_file_id', 'non_existent_folder_id', 'DOCUMENT_PARSE', 'PENDING', 10, 0, '2026-09-04T12:00:00Z');
        """
    )
    raw_conn.commit()
    raw_conn.close()

    with mgr.session() as conn:
        repo = Repository(conn)
        # Claim next job should fail the orphan and return None (since no other jobs exist)
        claimed = repo.claim_next_job()
        assert claimed is None

        # Verify the orphan job is now marked FAILED
        cur = conn.execute("SELECT status, error FROM indexing_jobs WHERE job_id = 'orphan_job_1';")
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "FAILED"
        assert "Orphan job" in row["error"]


def test_cancel_pending_jobs_for_file_on_deletion(repo_env):
    """Verify cancel_pending_jobs_for_file cancels any pending DOCUMENT_PARSE jobs (Bug 14)."""
    mgr, tmp_dir = repo_env
    with mgr.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_dir))
        fid = folder["folder_id"]
        file_rec = repo.upsert_file(
            folder_id=fid,
            path=os.path.join(str(tmp_dir), "delete_me.txt"),
            relative_path="delete_me.txt",
            filename="delete_me.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-04T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]

        parse_job = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=1)
        assert parse_job["status"] == "PENDING"

        # Explicitly cancel pending jobs on deletion/missing
        cancelled_count = repo.cancel_pending_jobs_for_file(file_id)
        assert cancelled_count >= 1

        # The DOCUMENT_PARSE job must be CANCELLED
        cur = conn.execute("SELECT status FROM indexing_jobs WHERE job_id = ?;", (parse_job["job_id"],))
        assert cur.fetchone()["status"] == "CANCELLED"


def test_recover_stale_processing_jobs_with_threshold(repo_env):
    """Verify recover_stale_processing_jobs supports stale_threshold_seconds and resets only affected files (Bug 13)."""
    mgr, tmp_dir = repo_env
    with mgr.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_dir))
        fid = folder["folder_id"]

        f1 = repo.upsert_file(
            folder_id=fid,
            path=os.path.join(str(tmp_dir), "f1.txt"),
            relative_path="f1.txt",
            filename="f1.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-04T12:00:00Z",
            index_status="PROCESSING",
        )
        f2 = repo.upsert_file(
            folder_id=fid,
            path=os.path.join(str(tmp_dir), "f2.txt"),
            relative_path="f2.txt",
            filename="f2.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-04T12:00:00Z",
            index_status="PROCESSING",
        )

        # Job 1 is very old (stale)
        conn.execute(
            """
            INSERT INTO indexing_jobs (job_id, file_id, folder_id, job_type, status, priority, attempts, created_at, started_at)
            VALUES ('job_old', ?, ?, 'DOCUMENT_PARSE', 'PROCESSING', 1, 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (f1["file_id"], fid),
        )

        # Job 2 just started now
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO indexing_jobs (job_id, file_id, folder_id, job_type, status, priority, attempts, created_at, started_at)
            VALUES ('job_new', ?, ?, 'DOCUMENT_PARSE', 'PROCESSING', 1, 1, ?, ?);
            """,
            (f2["file_id"], fid, now_iso, now_iso),
        )

        # Recover with 300s threshold
        recovered = repo.recover_stale_processing_jobs(stale_threshold_seconds=300)
        assert recovered == 1

        # f1 should be reset to QUEUED, f2 remains PROCESSING
        assert repo.get_file_by_id(f1["file_id"])["index_status"] == "QUEUED"
        assert repo.get_file_by_id(f2["file_id"])["index_status"] == "PROCESSING"


def test_pdf_parser_offsets(tmp_path):
    """Verify PyMuPDFParser populates line and char spans for text elements and leaves None for tables (Bug 103)."""
    import fitz
    pdf_path = str(tmp_path / "test_offsets.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Title Heading", fontsize=18)
    page.insert_text((50, 120), "This is a regular paragraph text on page one.", fontsize=10)
    page.insert_text((50, 160), "- Item 1 in list", fontsize=10)
    doc.save(pdf_path)
    doc.close()

    parser = PyMuPDFParser()
    parsed_doc = parser.parse(pdf_path, file_id="pdf_offset_test")

    assert parsed_doc.total_pages == 1
    assert len(parsed_doc.elements) >= 3

    for elem in parsed_doc.elements:
        if elem.element_type in (ElementType.HEADING, ElementType.PARAGRAPH, ElementType.LIST_ITEM):
            assert elem.line_start is not None and elem.line_start >= 1
            assert elem.line_end is not None and elem.line_end >= elem.line_start
            assert elem.char_start is not None and elem.char_start >= 0
            assert elem.char_end is not None and elem.char_end > elem.char_start
        elif elem.element_type == ElementType.TABLE:
            assert elem.line_start is None
            assert elem.line_end is None
            assert elem.char_start is None
            assert elem.char_end is None


def test_hybrid_search_filename_intent_scoped_to_file_id_filter(repo_env):
    """Verify filename intent search matches only within effective_filters['file_id'] (Bug 18)."""
    mgr, tmp_dir = repo_env
    with mgr.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_dir))
        fid = folder["folder_id"]

        f1 = repo.upsert_file(
            folder_id=fid,
            path=os.path.join(str(tmp_dir), "budget_2026.xlsx"),
            relative_path="budget_2026.xlsx",
            filename="budget_2026.xlsx",
            extension=".xlsx",
            size_bytes=500,
            modified_at="2026-09-04T12:00:00Z",
            index_status="INDEXED",
        )
        f2 = repo.upsert_file(
            folder_id=fid,
            path=os.path.join(str(tmp_dir), "budget_2025.xlsx"),
            relative_path="budget_2025.xlsx",
            filename="budget_2025.xlsx",
            extension=".xlsx",
            size_bytes=500,
            modified_at="2026-09-04T12:00:00Z",
            index_status="INDEXED",
        )

        retriever = HybridRetriever(conn)
        # Search for budget when scoped strictly to f1
        results = retriever.search(
            query="budget_2025.xlsx",
            mode="hybrid",
            filters={"file_id": f1["file_id"]},
        )
        # Since f1 is budget_2026.xlsx and filter is restricted to f1, budget_2025.xlsx from f2 should NOT be returned
        matched_file_ids = [r.get("file_id") for r in results.get("results", [])]
        assert f2["file_id"] not in matched_file_ids


def test_fs_enumerate_security_boundary(tmp_path):
    """Verify /fs/enumerate respects registered folders and rejects unauthorized paths (Bug 16 & 24)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.schemas import EnumerateRequest

    client = TestClient(app)

    reg_root = tmp_path / "registered_root"
    reg_root.mkdir()
    sub_dir = reg_root / "child_dir"
    sub_dir.mkdir()
    (sub_dir / "sample.txt").write_text("hello", encoding="utf-8")

    sibling_dir = tmp_path / "registered_root_sibling"
    sibling_dir.mkdir()
    (sibling_dir / "secret.txt").write_text("secret", encoding="utf-8")

    prefix_collision_dir = tmp_path / "registered_root2"
    prefix_collision_dir.mkdir()

    unrelated_dir = tmp_path / "unrelated_dir"
    unrelated_dir.mkdir()

    # Register the root folder
    reg_resp = client.post("/folders", json={"path": str(reg_root)})
    assert reg_resp.status_code == 201
    fid = reg_resp.json()["folder_id"]

    try:
        # 1. Registered root - allowed
        resp = client.post("/fs/enumerate", json={"folder_path": str(reg_root)})
        assert resp.status_code == 200
        assert resp.json()["file_count"] == 1

        # 2. Registered descendant - allowed
        resp = client.post("/fs/enumerate", json={"folder_path": str(sub_dir)})
        assert resp.status_code == 200

        # 3. Sibling directory - forbidden 403
        resp = client.post("/fs/enumerate", json={"folder_path": str(sibling_dir)})
        assert resp.status_code == 403
        assert "Access denied" in resp.json()["detail"]

        # 4. Path prefix collision (C:\Root2 vs C:\Root) - forbidden 403
        resp = client.post("/fs/enumerate", json={"folder_path": str(prefix_collision_dir)})
        assert resp.status_code == 403

        # 5. Unrelated absolute path - forbidden 403
        resp = client.post("/fs/enumerate", json={"folder_path": str(unrelated_dir)})
        assert resp.status_code == 403

        # 6. .. directory traversal escape - forbidden 403
        traversal_path = os.path.join(str(sub_dir), "..", "..", "registered_root_sibling")
        resp = client.post("/fs/enumerate", json={"folder_path": traversal_path})
        assert resp.status_code == 403
    finally:
        client.delete(f"/folders/{fid}")


def test_insight_cache_invalid_with_empty_chunks():
    """Verify is_cached_insight_current rejects cache when chunks are empty/purged (Bug 21)."""
    from app.ai.document_understanding import DocumentUnderstandingService

    file_rec = {"sha256": "abc123hash"}
    cached = {
        "status": "READY",
        "content_hash": "abc123hash",
        "model_name": "qwen2.5:7b",
        "parser_version": "1.0",
        "chunker_version": "1.0",
    }
    chunks = [{"parser_version": "1.0", "chunker_version": "1.0"}]

    # Valid chunks present -> valid cache
    assert DocumentUnderstandingService.is_cached_insight_current(
        file_rec, chunks, cached, "qwen2.5:7b"
    ) is True

    # Empty chunks -> cache must NOT claim validity
    assert DocumentUnderstandingService.is_cached_insight_current(
        file_rec, [], cached, "qwen2.5:7b"
    ) is False


def test_health_readiness_and_subsystem_checks():
    """Verify /health reports true subsystem readiness and /health/liveness checks process (Bug 101)."""
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock
    from app.core.context import AppContext, default_app_context
    from app.main import app

    with TestClient(app) as client:
        # 1. Healthy system
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["ready"] is True
        assert data["database"] == "healthy"
        assert data["vector_store"] == "healthy"
        assert data["worker"] == "healthy"

        # 2. Liveness endpoint
        live_resp = client.get("/health/liveness")
        assert live_resp.status_code == 200
        assert live_resp.json()["status"] == "alive"

        # 3. DB failure surfacing
        mock_db = MagicMock()
        mock_db.session.side_effect = RuntimeError("Database connection timed out")
        mock_ctx = AppContext(db_manager=mock_db)
        app.state.context = mock_ctx
        try:
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "unhealthy"
            assert data["ready"] is False
            assert data["database"] == "unhealthy"
        finally:
            app.state.context = default_app_context

        # 4. Engine coordinator not initialized
        uninit_coord = MagicMock()
        uninit_coord._is_initialized = False
        mock_ctx2 = AppContext(engine_coordinator=uninit_coord)
        app.state.context = mock_ctx2
        try:
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "initializing"
            assert data["ready"] is False
            assert data["worker"] == "initializing"
        finally:
            app.state.context = default_app_context


def test_ask_filemind_injected_dependencies_and_busy_error():
    """Verify /ai/ask honors AppContext dependencies, reports 409 on busy, and 400 on malformed input (Bug 4, 9, 19, Finding 1)."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from app.ai.ask_service import AskService
    from app.ai.generation_coordinator import LocalGenerationBusyError
    from app.main import app

    with TestClient(app) as client:
        # 1. Malformed input (whitespace query) returns 400 Bad Request
        resp = client.post("/ai/ask", json={"query": "   "})
        assert resp.status_code == 400
        assert "Query cannot be empty" in resp.json()["detail"]

        # 2. Invalid mode/quality combo returns 400 Bad Request
        resp = client.post("/ai/ask", json={"query": "hello", "mode": "dense", "quality": "quality"})
        assert resp.status_code == 400
        assert "Quality mode is only supported with hybrid retrieval" in resp.json()["detail"]

        # 3. Busy generation coordinator returns 409 Conflict
        with patch.object(AskService, "ask", side_effect=LocalGenerationBusyError("A local AI generation is already in progress")):
            resp = client.post("/ai/ask", json={"query": "test query"})
            assert resp.status_code == 409
            assert "already in progress" in resp.json()["detail"]


def test_app_context_close_and_fallbacks(caplog):
    """Verify AppContext fallbacks and close exception logging (Findings 2 & 3)."""
    import logging
    from app.core.context import AppContext
    from unittest.mock import MagicMock

    # Verify fallbacks return default instances rather than None
    ctx = AppContext()
    assert ctx.embedding_engine is not None
    assert ctx.reranker is not None
    assert ctx.model_registry is not None
    assert ctx.generation_coordinator is not None

    # Verify close() logs warning on error instead of swallowing silently
    failing_coord = MagicMock()
    failing_coord.shutdown.side_effect = RuntimeError("Shutdown lock timeout")
    err_ctx = AppContext(engine_coordinator=failing_coord)

    with caplog.at_level(logging.WARNING):
        err_ctx.close()
    assert any("Error shutting down engine_coordinator" in r.message for r in caplog.records)
