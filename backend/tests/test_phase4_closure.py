"""Phase 4 Closure Test Suite: Fast / Quality Semantics, Degradation, Validation, and Provenance.

Verifies:
1. Valid mode + quality combinations (BM25+Fast, Dense+Fast, Hybrid+Fast, Hybrid+Quality).
2. Explicit rejection of invalid combinations (BM25+Quality, Dense+Quality, bad modes).
3. Exact Fast vs Quality pipeline execution and score semantics.
4. Explicit Quality degradation when reranker fails or is unavailable.
5. Candidate pool dynamic expansion when top_k > candidate_pool_size.
6. Timing provenance propagation across all stages.
7. Deterministic tie-breaking and score ordering.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import SqliteVecStore
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


@pytest.fixture
def test_vault(tmp_path):
    """Sets up an isolated test vault with indexed documents and vectors."""
    target_dir = str(tmp_path / "docs")
    db_path = str(tmp_path / "test_p4.db")
    meta = setup_benchmark_corpus(target_dir, db_path)
    db = DatabaseManager(db_path)
    return db, meta


def test_api_valid_combinations_and_schemas(test_vault):
    """Verifies that all valid mode + quality combinations succeed through the API."""
    db, meta = test_vault
    client = TestClient(app)

    with patch("app.main.db_manager", db):
        # 1. BM25 + Fast
        res = client.post("/search", json={"query": "system architecture", "mode": "bm25", "quality": "fast", "top_k": 5})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["mode"] == "bm25"
        assert data["quality"] == "fast"
        assert data["degraded"] is False
        assert len(data["results"]) > 0
        for r in data["results"]:
            assert r["reranker_score"] is None
            assert r["lexical_score"] is not None

        # 2. Dense + Fast
        res = client.post("/search", json={"query": "system architecture", "mode": "dense", "quality": "fast", "top_k": 5})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["mode"] == "dense"
        assert data["quality"] == "fast"
        assert data["degraded"] is False
        for r in data["results"]:
            assert r["reranker_score"] is None
            assert r["dense_score"] is not None

        # 3. Hybrid + Fast
        res = client.post("/search", json={"query": "system architecture", "mode": "hybrid", "quality": "fast", "top_k": 5})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["mode"] == "hybrid"
        assert data["quality"] == "fast"
        assert data["degraded"] is False
        for r in data["results"]:
            assert r["reranker_score"] is None
            assert r["rrf_score"] is not None

        # 4. Hybrid + Quality
        res = client.post("/search", json={"query": "system architecture", "mode": "hybrid", "quality": "quality", "top_k": 5})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["mode"] == "hybrid"
        assert data["quality"] == "quality"


def test_api_invalid_combinations_rejected(test_vault):
    """Verifies that unsupported mode + quality combinations return explicit 400 Bad Request errors."""
    db, meta = test_vault
    client = TestClient(app)

    with patch("app.main.db_manager", db):
        # BM25 + Quality -> 400
        res = client.post("/search", json={"query": "test query", "mode": "bm25", "quality": "quality"})
        assert res.status_code == 400
        assert "Quality mode is only supported with hybrid retrieval" in res.json()["detail"]

        # Dense + Quality -> 400
        res = client.post("/search", json={"query": "test query", "mode": "dense", "quality": "quality"})
        assert res.status_code == 400
        assert "Quality mode is only supported with hybrid retrieval" in res.json()["detail"]

        # Invalid mode -> 400
        res = client.post("/search", json={"query": "test query", "mode": "unknown_mode", "quality": "fast"})
        assert res.status_code == 400
        assert "Invalid retrieval mode" in res.json()["detail"]

        # Invalid quality -> 400
        res = client.post("/search", json={"query": "test query", "mode": "hybrid", "quality": "ultra_hd"})
        assert res.status_code == 400
        assert "Invalid quality mode" in res.json()["detail"]


def test_quality_degradation_when_reranker_fails(test_vault):
    """Verifies that Quality search gracefully degrades to RRF when the reranker fails."""
    db, meta = test_vault

    mock_reranker = MagicMock()
    mock_reranker.rerank.side_effect = RuntimeError("ONNX inference device memory error")

    with db.session() as conn:
        retriever = HybridRetriever(
            db_conn=conn,
            reranker=mock_reranker,
        )

        res = retriever.search(
            query="system architecture specification",
            top_k=5,
            mode="hybrid",
            quality="quality",
        )

        assert res["quality"] == "quality"
        assert res["degraded"] is True
        assert "reranker_unavailable" in res["degraded_reason"]
        assert len(res["results"]) > 0
        # When degraded, reranker_score must be None and RRF score preserved
        for r in res["results"]:
            assert r["reranker_score"] is None
            assert r["rrf_score"] is not None
            assert r["score"] == r["rrf_score"]


def test_dynamic_candidate_pool_expansion(test_vault):
    """Verifies that requesting top_k > candidate_pool_size dynamically expands the candidate pool."""
    db, meta = test_vault

    mock_reranker = MagicMock()
    # Mock rerank to return candidate count
    mock_reranker.rerank.side_effect = lambda query, candidates, top_k: [
        {**c, "reranker_score": 0.95, "score": 0.95, "rank": i + 1}
        for i, c in enumerate(candidates[:top_k])
    ]

    with db.session() as conn:
        retriever = HybridRetriever(
            db_conn=conn,
            reranker=mock_reranker,
            rerank_candidate_pool_size=10,  # default pool small
        )

        # Request top_k = 30 > candidate_pool_size (10)
        res = retriever.search(
            query="spec",
            top_k=30,
            mode="hybrid",
            quality="quality",
        )

        # Verify mock reranker received at least 30 candidates (dynamic pool expansion)
        assert mock_reranker.rerank.called
        call_args = mock_reranker.rerank.call_args
        candidates_passed = call_args[1]["candidates"]
        assert len(candidates_passed) >= min(30, len(meta["chunks"]))


def test_timing_provenance_propagation(test_vault):
    """Verifies that all required timing stages are computed and returned."""
    db, meta = test_vault

    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)
        res = retriever.search(
            query="cryptographic hashing",
            top_k=5,
            mode="hybrid",
            quality="fast",
        )

        lat = res["latency_breakdown_ms"]
        required_stages = [
            "normalization",
            "lexical_search",
            "query_embedding",
            "dense_search",
            "rrf_fusion",
            "reranker_inference",
            "total_request",
        ]
        for stage in required_stages:
            assert stage in lat
            assert isinstance(lat[stage], (int, float))
            assert lat[stage] >= 0.0

        assert lat["reranker_inference"] == 0.0  # Fast mode does not run reranker


def test_deterministic_ranking_and_tie_breaking(test_vault):
    """Verifies that repeated searches produce identical, deterministic results with tie-breaking."""
    db, meta = test_vault

    with db.session() as conn:
        retriever = HybridRetriever(db_conn=conn)
        res1 = retriever.search(query="storage engine WAL", top_k=5, mode="hybrid", quality="fast")
        res2 = retriever.search(query="storage engine WAL", top_k=5, mode="hybrid", quality="fast")

        assert [r["chunk_id"] for r in res1["results"]] == [r["chunk_id"] for r in res2["results"]]
        assert [r["score"] for r in res1["results"]] == [r["score"] for r in res2["results"]]
