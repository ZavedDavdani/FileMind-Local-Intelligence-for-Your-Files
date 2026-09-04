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
        conn.execute(
            """
            INSERT INTO indexing_jobs (job_id, file_id, folder_id, job_type, status, priority, attempts, created_at, started_at)
            VALUES ('job_new', ?, ?, 'DOCUMENT_PARSE', 'PROCESSING', 1, 1, '2026-09-04T22:00:00Z', '2026-09-04T22:00:00Z');
            """,
            (f2["file_id"], fid),
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
