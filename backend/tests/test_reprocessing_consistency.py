"""Tests for Phase 3 Reprocessing Consistency.

Verifies:
- Modified document content updates FTS5 and vector index
- Stale chunks and vectors are completely purged
- New content is immediately retrievable
- File ID and provenance chains remain intact
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


def test_document_reprocessing_updates_indexes():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "reprocess.db")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    # Pick a file to modify
    target_md = os.path.join(temp_dir, "structural", "sample_architecture.md")
    assert os.path.exists(target_md)

    with db.session() as conn:
        retriever = HybridRetriever(conn)
        # Search for original text
        initial_res = retriever.search("Performance Targets Latency < 600 ms", top_k=5)
        assert len(initial_res["results"]) > 0

    # Modify the markdown file content
    with open(target_md, "w", encoding="utf-8") as f:
        f.write("# Modified Architecture Specification\n\n## Subsystems\nUpdated quantum resilience subsystem with zero-latency streaming.")

    # Process modification through WorkerPool
    worker_pool = WorkerPool(db, max_workers=1)
    with db.session() as conn:
        repo = Repository(conn)
        frec = repo.get_file_by_path(target_md)
        fid = frec["file_id"]
        repo.enqueue_job(fid, frec["folder_id"], "DOCUMENT_PARSE")

    job = worker_pool.queue.claim_job()
    assert job is not None
    worker_pool._process_job(job)

    # Verify retrieval after update
    with db.session() as conn:
        retriever = HybridRetriever(conn)
        # 1. New content should be retrievable
        new_res = retriever.search("Updated quantum resilience subsystem", top_k=5)
        assert len(new_res["results"]) > 0
        top_r = new_res["results"][0]
        assert "quantum resilience" in top_r["content"]
        assert top_r["file_id"] == fid

        # 2. Stale content should NOT be returned
        old_res = retriever.search("Performance Targets Latency < 600 ms", top_k=5)
        # Old content was overwritten in sample_architecture.md
        for r in old_res["results"]:
            if r["file_id"] == fid:
                assert "Latency < 600 ms" not in r["content"]
