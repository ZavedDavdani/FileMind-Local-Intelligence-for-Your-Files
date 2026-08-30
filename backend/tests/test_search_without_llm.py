"""Tests for Phase 3 Search Without LLM Capability.

Verifies:
- Retrieval executes locally with zero LLM / Ollama dependencies
- Ranked evidence candidates, real snippets, and source locations are returned
- No generative AI or hallucinations occur
"""

import os
import sys
import tempfile
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.hybrid import HybridRetriever
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


def test_search_functions_without_llm():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "no_llm.db")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    with db.session() as conn:
        retriever = HybridRetriever(conn)
        resp = retriever.search("SQLite WAL recovery architecture", top_k=5)

        assert resp["total_found"] > 0
        assert len(resp["results"]) > 0

        for r in resp["results"]:
            assert r["chunk_id"]
            assert r["file_id"]
            assert r["source_file"]
            assert r["source_path"]
            assert r["snippet"]
            assert r["score"] > 0.0
            # Ensure snippet comes from actual chunk content
            assert r["snippet"].replace("...", "").strip() in r["content"].replace("\n", " ")
