"""Tests for Phase 3 Retrieval Security & Filter Boundary Isolation."""

import os
import sys
import tempfile
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.hybrid import HybridRetriever
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


def test_sql_injection_payloads_safely_handled():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "sec_test.db")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    malicious_queries = [
        "'; DROP TABLE chunks; --",
        "' OR '1'='1",
        "UNION SELECT * FROM files --",
        "\" OR 1=1 --",
        "'; DELETE FROM folders; --",
        "NEAR/0 (a, b)",
    ]

    with db.session() as conn:
        retriever = HybridRetriever(conn)
        for q in malicious_queries:
            resp = retriever.search(q, top_k=5)
            assert isinstance(resp, dict)
            assert "results" in resp

        # Verify tables still exist
        cur = conn.execute("SELECT COUNT(*) FROM chunks;")
        assert cur.fetchone()[0] > 0
        cur2 = conn.execute("SELECT COUNT(*) FROM folders;")
        assert cur2.fetchone()[0] > 0


def test_folder_containment_and_isolation():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "folder_sec.db")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    fake_folder_id = "nonexistent_folder_id_999"

    with db.session() as conn:
        retriever = HybridRetriever(conn)
        # Search with unauthorized / nonexistent folder_id
        res = retriever.search("Architecture", filters={"folder_id": fake_folder_id})
        assert res["total_found"] == 0
        assert len(res["results"]) == 0
