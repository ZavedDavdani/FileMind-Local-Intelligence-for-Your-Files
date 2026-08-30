"""Unit tests for Phase 3 SQLite FTS5 / BM25 Lexical Retrieval."""

import os
import sys
import tempfile
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.lexical import LexicalRetriever
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


@pytest.fixture
def corpus_env():
    td = tempfile.mkdtemp()
    db_path = os.path.join(td, "lexical_test.db")
    meta = setup_benchmark_corpus(td, db_path)
    db = DatabaseManager(db_path)
    yield db, meta


def test_bm25_exact_phrase(corpus_env):
    db, meta = corpus_env
    with db.session() as conn:
        retriever = LexicalRetriever(conn)
        results = retriever.search('"Cryptographic hashing with streaming SHA-256 validation"', top_k=5)
        assert len(results) > 0
        top_res = results[0]
        assert top_res["source_file"] == "doc1_enterprise_spec.pdf"
        assert "Cryptographic hashing" in top_res["content"]
        assert top_res["chunk_id"].startswith("chk_")
        assert top_res["retrieval_method"] == "bm25"
        assert top_res["rank"] == 1


def test_bm25_metadata_filtering(corpus_env):
    db, meta = corpus_env
    with db.session() as conn:
        retriever = LexicalRetriever(conn)
        # Search for Performance with PDF extension filter
        pdf_results = retriever.search("Performance", filters={"extension": ".pdf"})
        for r in pdf_results:
            assert r["source_file"].endswith(".pdf")

        # Search for Performance with XLSX extension filter
        xlsx_results = retriever.search("Performance", filters={"extension": "xlsx"})
        for r in xlsx_results:
            assert r["source_file"].endswith(".xlsx")


def test_bm25_deterministic_ranking(corpus_env):
    db, meta = corpus_env
    with db.session() as conn:
        retriever = LexicalRetriever(conn)
        res1 = retriever.search("SQLite WAL architecture persistence", top_k=10)
        res2 = retriever.search("SQLite WAL architecture persistence", top_k=10)
        assert [r["chunk_id"] for r in res1] == [r["chunk_id"] for r in res2]


def test_bm25_empty_query(corpus_env):
    db, meta = corpus_env
    with db.session() as conn:
        retriever = LexicalRetriever(conn)
        assert retriever.search("") == []
        assert retriever.search("   ") == []
