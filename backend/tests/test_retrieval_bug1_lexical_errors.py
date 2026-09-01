"""Tests for Bug #1: Lexical retrieval error propagation and graceful hybrid degradation."""

import os
import sqlite3
import tempfile
import unittest.mock as mock
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.provenance import ChunkProvenance
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def test_env():
    """Sets up an isolated database with test file, chunk, and vector records."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_bug1.db")
        db = DatabaseManager(db_path)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(tmp_dir)

            file_path = os.path.join(tmp_dir, "sample.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Sample document content for hybrid testing.")

            f = repo.upsert_file(
                folder_id=folder["folder_id"],
                path=file_path,
                relative_path="sample.txt",
                filename="sample.txt",
                extension=".txt",
                size_bytes=os.path.getsize(file_path),
                modified_at="2026-08-30T12:00:00Z",
                file_id="f_sample_01",
            )

            chunk = ChunkProvenance(
                chunk_id="chk_sample_01",
                file_id="f_sample_01",
                source_file="sample.txt",
                source_path=file_path,
                content="Sample document content for hybrid testing.",
                h1_parent="Sample",
                section="Sample",
                line_start=1,
                line_end=1,
            )
            repo.replace_file_chunks("f_sample_01", [chunk])

            vec_store = SqliteVecStore(conn, dimension=384)
            vec_store.upsert_vectors([{
                "chunk_id": "chk_sample_01",
                "file_id": "f_sample_01",
                "embedding": [0.1] * 384,
            }])

        yield db, tmp_dir


def test_bug1_lexical_retriever_propagates_sqlite_operational_error():
    """Bug #1: LexicalRetriever.search() MUST NOT swallow sqlite3.OperationalError into []."""
    conn = sqlite3.connect(":memory:")
    # No chunks_fts or chunks tables exist in this raw in-memory connection
    retriever = LexicalRetriever(conn)

    with pytest.raises(sqlite3.OperationalError):
        retriever.search("sample")


def test_bug1_hybrid_retriever_bm25_mode_propagates_lexical_failure(test_env):
    """Bug #1: In mode='bm25', a lexical retrieval failure propagates as a real subsystem error."""
    db, _ = test_env
    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)

        # Simulate lexical execution failure
        with mock.patch.object(retriever.lexical_retriever, "search", side_effect=sqlite3.OperationalError("database disk image is malformed")):
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                retriever.search("sample", mode="bm25")
            assert "malformed" in str(exc_info.value)


def test_bug1_hybrid_mode_degrades_to_dense_fallback_on_lexical_failure(test_env):
    """Bug #1: In mode='hybrid', when lexical search fails and dense succeeds, it gracefully degrades to dense_fallback."""
    db, _ = test_env
    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)

        with mock.patch.object(retriever.lexical_retriever, "search", side_effect=sqlite3.OperationalError("FTS5 table missing")):
            resp = retriever.search("hybrid testing", mode="hybrid")

            assert resp["mode"] == "hybrid"
            assert resp["degraded"] is True
            assert "lexical_retrieval_unavailable" in resp["degraded_reason"]
            assert resp["retrieval_method"] == "dense_fallback"
            assert resp["total_found"] > 0

            top = resp["results"][0]
            assert top["chunk_id"] == "chk_sample_01"
            assert top["dense_score"] is not None
            assert top["lexical_score"] is None
            assert top["rrf_score"] is None
            assert top["retrieval_method"] == "dense_fallback"


def test_bug1_hybrid_mode_raises_when_both_lexical_and_dense_fail(test_env):
    """Bug #1: In mode='hybrid', if both lexical and dense search fail, a RuntimeError is raised."""
    db, _ = test_env
    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)

        with mock.patch.object(retriever.lexical_retriever, "search", side_effect=sqlite3.OperationalError("FTS5 table corrupted")):
            with mock.patch.object(retriever.vector_store, "search", side_effect=RuntimeError("Vector index inaccessible")):
                with pytest.raises(RuntimeError) as exc_info:
                    retriever.search("sample", mode="hybrid")
                assert "Both lexical and dense retrieval failed" in str(exc_info.value)


def test_bug1_legitimate_zero_result_query_is_non_error(test_env):
    """Bug #1: Legitimate zero-result queries return an empty list without error or degraded flag."""
    db, _ = test_env
    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)
        # BM25 zero results
        resp = retriever.search("completely_non_existent_token_xyz987", mode="bm25")
        assert resp["total_found"] == 0
        assert resp["results"] == []
        assert resp["degraded"] is False
        assert resp["degraded_reason"] is None
        assert resp["retrieval_method"] == "bm25"

        # Hybrid zero results with non-matching filter
        resp_filt = retriever.search("sample", mode="hybrid", filters={"extension": ".pdf"})
        assert resp_filt["total_found"] == 0
        assert resp_filt["results"] == []
        assert resp_filt["degraded"] is False
        assert resp_filt["degraded_reason"] is None
        assert resp_filt["retrieval_method"] == "hybrid"


def test_bug1_lexical_failure_is_distinguishable_from_zero_results(test_env):
    """Bug #1: Proves that zero-result searches have degraded=False, whereas subsystem failures degrade or raise."""
    db, _ = test_env
    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)

        # 1. Zero results in BM25 mode
        zero_resp = retriever.search("unmatched_token_abc_123", mode="bm25")
        assert zero_resp["degraded"] is False
        assert zero_resp["total_found"] == 0

        # 2. Simulated lexical failure in Hybrid mode
        with mock.patch.object(retriever.lexical_retriever, "search", side_effect=sqlite3.OperationalError("disk I/O error")):
            degraded_resp = retriever.search("unmatched_token_abc_123", mode="hybrid")
            assert degraded_resp["degraded"] is True
            assert "lexical_retrieval_unavailable" in degraded_resp["degraded_reason"]
            assert degraded_resp["retrieval_method"] == "dense_fallback"
