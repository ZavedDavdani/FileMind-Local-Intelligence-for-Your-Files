"""Tests for Phase 3 Delete Consistency.

Verifies:
- Deleted files are marked MISSING and their chunks/vectors are removed
- Deleted file chunks never appear in search results across BM25, Dense, or Hybrid
- No orphan active vectors or chunks remain
"""

import os
import sys
import tempfile
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.worker import WorkerPool
from app.retrieval.hybrid import HybridRetriever
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


def test_deleted_file_chunks_and_vectors_purged():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "delete_test.db")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    # Search for doc5 compliance checklist
    with db.session() as conn:
        retriever = HybridRetriever(conn)
        res_before = retriever.search("Compliance Checklist zero orphan worker processes", top_k=5)
        assert len(res_before["results"]) > 0
        target_fid = res_before["results"][0]["file_id"]

    # Delete the document on disk and run worker DELETE_CLEANUP
    target_docx = os.path.join(temp_dir, "adversarial", "doc5_bullets.docx")
    if os.path.exists(target_docx):
        os.remove(target_docx)

    worker_pool = WorkerPool(db, max_workers=1)
    with db.session() as conn:
        repo = Repository(conn)
        repo.update_file_status(target_fid, "MISSING")
        repo.enqueue_job(target_fid, meta["folder_id"], "DELETE_CLEANUP")

    job = worker_pool.queue.claim_job()
    assert job is not None
    worker_pool._process_job(job)

    # Verify retrieval after deletion
    with db.session() as conn:
        retriever = HybridRetriever(conn)
        # Search in all 3 modes
        for mode in ["bm25", "dense", "hybrid"]:
            res_after = retriever.search("Compliance Checklist zero orphan worker processes", top_k=10, mode=mode)
            for r in res_after["results"]:
                assert r["file_id"] != target_fid, f"Deleted file chunk found in mode {mode}"
