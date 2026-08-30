"""Phase 3 Retrieval Hardening: Hybrid Retrieval Vector Fallback and Graceful Degradation Tests.

Validates:
1. Normal hybrid operation with RRF fusion.
2. Graceful fallback to BM25 when vector store / embedding inference is unavailable.
3. Explicit degraded response state (degraded=True, degraded_reason, retrieval_method="bm25_fallback").
4. No fabricated dense scores during fallback (dense_score=None, rrf_score=None).
5. Unbroken provenance preservation during fallback.
6. Deterministic BM25 ranking ordering during fallback.
7. Unchanged BM25-only behavior.
8. Controlled failure preservation for dense-only queries.
9. Seamless recovery to normal hybrid retrieval when vector store restores availability.
10. API endpoint contract compliance with SearchResponse schema.
"""

import os
import sqlite3
import tempfile
import unittest.mock as mock
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.provenance import ChunkProvenance
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_store import SqliteVecStore
from app.schemas import SearchResponse


@pytest.fixture
def fallback_test_setup():
    """Sets up an isolated database with test file, chunk, and vector records."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_fallback.db")
        db = DatabaseManager(db_path)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(tmp_dir)

            file_path = os.path.join(tmp_dir, "architecture_spec.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# Architecture\n\nCore SQLite storage engine specifications and indexing.")

            f = repo.upsert_file(
                folder_id=folder["folder_id"],
                path=file_path,
                relative_path="architecture_spec.md",
                filename="architecture_spec.md",
                extension=".md",
                size_bytes=os.path.getsize(file_path),
                modified_at="2026-08-30T12:00:00Z",
                file_id="f_arch_001",
            )

            chunk1 = ChunkProvenance(
                chunk_id="chk_arch_core",
                file_id="f_arch_001",
                source_file="architecture_spec.md",
                source_path=file_path,
                content="Core SQLite storage engine specifications and indexing.",
                h1_parent="Architecture",
                section="Architecture",
                line_start=1,
                line_end=3,
            )
            repo.replace_file_chunks("f_arch_001", [chunk1])

            vec_store = SqliteVecStore(conn, dimension=384)
            vec_store.upsert_vectors([{"chunk_id": "chk_arch_core", "file_id": "f_arch_001", "embedding": [0.05] * 384}])

        yield db, tmp_dir


def test_1_normal_hybrid_operation(fallback_test_setup):
    """Test 1: Normal hybrid operation returns RRF fused results with full scores."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)
        resp = retriever.search("SQLite storage engine", mode="hybrid")

        assert resp["mode"] == "hybrid"
        assert resp["degraded"] is False
        assert resp["degraded_reason"] is None
        assert resp["retrieval_method"] == "hybrid"
        assert resp["total_found"] > 0

        first = resp["results"][0]
        assert first["chunk_id"] == "chk_arch_core"
        assert first["rrf_score"] is not None
        assert first["retrieval_method"] == "hybrid"


def test_2_and_3_simulated_vector_failure_hybrid_fallback(fallback_test_setup):
    """Test 2 & 3: Vector store failure gracefully degrades hybrid search to BM25 fallback."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        mock_vec_store = mock.MagicMock()
        mock_vec_store.search.side_effect = RuntimeError("sqlite-vec extension table locked or corrupted")

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec_store)
        resp = retriever.search("SQLite storage engine", mode="hybrid")

        # Must not crash, must return BM25 results
        assert resp["mode"] == "hybrid"
        assert resp["degraded"] is True
        assert "dense_retrieval_unavailable" in resp["degraded_reason"]
        assert resp["retrieval_method"] == "bm25_fallback"
        assert resp["total_found"] > 0


def test_4_no_fabricated_dense_scores_during_fallback(fallback_test_setup):
    """Test 4: Fallback results have no fabricated dense or RRF scores."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        mock_vec_store = mock.MagicMock()
        mock_vec_store.search.side_effect = RuntimeError("Vector backend offline")

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec_store)
        resp = retriever.search("SQLite storage engine", mode="hybrid")

        first = resp["results"][0]
        assert first["dense_score"] is None
        assert first["dense_rank"] is None
        assert first["rrf_score"] is None
        assert first["lexical_score"] is not None
        assert first["score"] == first["lexical_score"]
        assert first["retrieval_method"] == "bm25_fallback"


def test_5_and_6_provenance_and_ranking_preserved(fallback_test_setup):
    """Test 5 & 6: Provenance metadata and ranking order are strictly preserved."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        mock_vec_store = mock.MagicMock()
        mock_vec_store.search.side_effect = RuntimeError("Embedding timeout")

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec_store)
        resp = retriever.search("storage engine", mode="hybrid")

        first = resp["results"][0]
        assert first["chunk_id"] == "chk_arch_core"
        assert first["file_id"] == "f_arch_001"
        assert first["source_file"] == "architecture_spec.md"
        assert first["h1_parent"] == "Architecture"
        assert first["rank"] == 1


def test_7_explicit_degraded_state(fallback_test_setup):
    """Test 7: Response root contains explicit degradation telemetry."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        mock_vec_store = mock.MagicMock()
        mock_vec_store.search.side_effect = RuntimeError("Simulated vector OOM")

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec_store)
        resp = retriever.search("storage engine", mode="hybrid")

        assert resp["degraded"] is True
        assert "Simulated vector OOM" in resp["degraded_reason"]


def test_8_bm25_only_mode_unaffected(fallback_test_setup):
    """Test 8: BM25-only mode continues functioning normally without touching vector store."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        mock_vec_store = mock.MagicMock()
        mock_vec_store.search.side_effect = RuntimeError("Broken vector store")

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec_store)
        resp = retriever.search("storage engine", mode="bm25")

        assert resp["mode"] == "bm25"
        assert resp["degraded"] is False
        assert len(resp["results"]) > 0
        mock_vec_store.search.assert_not_called()


def test_9_dense_only_mode_raises_controlled_exception(fallback_test_setup):
    """Test 9: Dense-only mode raises controlled exception when vector backend is unavailable."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        mock_vec_store = mock.MagicMock()
        mock_vec_store.search.side_effect = RuntimeError("Hardware accelerator error")

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec_store)
        with pytest.raises(RuntimeError) as exc_info:
            retriever.search("storage engine", mode="dense")
        assert "Hardware accelerator error" in str(exc_info.value)


def test_10_recovery_when_vector_store_restored(fallback_test_setup):
    """Test 10: System automatically recovers to normal hybrid mode when vector store recovers."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        vec_store = SqliteVecStore(conn, dimension=384)
        mock_engine = mock.MagicMock(wraps=EmbeddingEngine("sentence-transformers/all-MiniLM-L6-v2"))

        # Step 1: Simulate temporary failure
        mock_engine.embed_query.side_effect = [RuntimeError("Temporary GPU OOM"), [0.05] * 384]

        retriever = HybridRetriever(
            db_conn=conn,
            embedding_engine=mock_engine,
            vector_store=vec_store,
        )

        # Call 1: Degraded
        resp1 = retriever.search("storage engine", mode="hybrid")
        assert resp1["degraded"] is True
        assert resp1["retrieval_method"] == "bm25_fallback"

        # Call 2: Recovered
        resp2 = retriever.search("storage engine", mode="hybrid")
        assert resp2["degraded"] is False
        assert resp2["retrieval_method"] == "hybrid"
        assert resp2["results"][0]["rrf_score"] is not None


def test_schema_serialization_contract(fallback_test_setup):
    """Test: Validates that degraded responses serialize cleanly into FastAPI SearchResponse schema."""
    db, _ = fallback_test_setup
    with db.session() as conn:
        mock_vec_store = mock.MagicMock()
        mock_vec_store.search.side_effect = RuntimeError("Vector store offline")

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec_store)
        resp = retriever.search("storage engine", mode="hybrid")

        # Must pass Pydantic schema validation without error
        validated = SearchResponse(**resp)
        assert validated.degraded is True
        assert validated.retrieval_method == "bm25_fallback"
        assert len(validated.results) > 0
