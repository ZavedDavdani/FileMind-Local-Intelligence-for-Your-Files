"""Phase 4 Test Suite: Cross-Encoder Reranking Layer (BAAI/bge-reranker-base).

Validates:
1. Reranker interface test (query, candidates, top_k contract).
2. Candidate count limiting (respects rerank_candidate_pool_size and top_k).
3. Deterministic ordering with multi-level tie-breaking.
4. Reranker score field presence (reranker_score is float).
5. Existing lexical, dense, and RRF scores preserved without fabrication/loss.
6. Complete provenance preservation (source_file, source_path, page, section, h1/h2, lines, chars, hash, chunk_id, file_id).
7. BM25-only candidate preserves dense_score = None.
8. Dense-only candidate preserves lexical_score = None.
9. Reranker unavailable / failure gracefully falls back to RRF ranking (degraded=True, reranker_score=None).
10. Reranker failure does not destroy valid hybrid retrieval results.
11. Existing filters remain strictly enforced before reranking.
12. Empty candidate pool handled safely.
13. top_k smaller than reranker pool returns exact top_k results.
14. top_k larger than available candidates returns all available candidates.
15. Duplicate/equal scores handled with deterministic tie-breaking.
16. Model loaded once and reused across invocations (fast path).
17. No model reload per request.
18. Latency stages independently measured without double-counting (reranker_inference present).
19. Search modes scope: BM25-only and Dense-only modes bypass reranking (reranker_score = None).
20. Real cross-encoder semantic reordering test.
"""

import os
import sqlite3
import tempfile
import time
import unittest.mock as mock
import pytest
from typing import Any, Dict, List, Optional

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.provenance import ChunkProvenance
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import Reranker, RerankerLoadTimeoutError, _sigmoid
from app.retrieval.vector_store import SqliteVecStore
from app.schemas import SearchResponse


class MockCrossEncoderModel:
    """Deterministic mock cross-encoder for unit testing without ONNX weights."""

    def __init__(self, score_mapping: Optional[Dict[str, float]] = None, default_score: float = 0.5):
        self.score_mapping = score_mapping or {}
        self.default_score = default_score
        self.call_count = 0

    def rerank(self, query: str, documents: List[str], batch_size: int = 32):
        self.call_count += 1
        for doc in documents:
            yield self.score_mapping.get(doc, self.default_score)


@pytest.fixture
def phase4_test_setup():
    """Sets up an isolated test database with 3 documents and multiple chunks."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_phase4.db")
        db = DatabaseManager(db_path)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(tmp_dir)
            fld_id = folder["folder_id"]

            # Doc 1: Architecture
            f1_path = os.path.join(tmp_dir, "arch.md")
            with open(f1_path, "w", encoding="utf-8") as f:
                f.write("# Architecture\nCore storage engine specifications.")
            repo.upsert_file(
                folder_id=fld_id,
                path=f1_path,
                relative_path="arch.md",
                filename="arch.md",
                extension=".md",
                size_bytes=os.path.getsize(f1_path),
                modified_at="2026-08-30T12:00:00Z",
                file_id="f_arch",
            )
            c1 = ChunkProvenance(
                chunk_id="chk_arch_1",
                file_id="f_arch",
                source_file="arch.md",
                source_path=f1_path,
                content="Core storage engine specifications and SQLite WAL configuration.",
                h1_parent="Architecture",
                section="Architecture",
                page=1,
                line_start=1,
                line_end=2,
                char_start=0,
                char_end=65,
            )

            # Doc 2: Security Spec
            f2_path = os.path.join(tmp_dir, "sec.pdf")
            with open(f2_path, "w", encoding="utf-8") as f:
                f.write("Security subsystem hierarchy and cryptographic SHA-256 verification.")
            repo.upsert_file(
                folder_id=fld_id,
                path=f2_path,
                relative_path="sec.pdf",
                filename="sec.pdf",
                extension=".pdf",
                size_bytes=os.path.getsize(f2_path),
                modified_at="2026-08-30T12:00:00Z",
                file_id="f_sec",
            )
            c2 = ChunkProvenance(
                chunk_id="chk_sec_1",
                file_id="f_sec",
                source_file="sec.pdf",
                source_path=f2_path,
                content="Security subsystem hierarchy and cryptographic SHA-256 verification.",
                h1_parent="Security",
                section="Security",
                page=2,
                line_start=1,
                line_end=1,
                char_start=0,
                char_end=70,
            )

            # Doc 3: Notes
            f3_path = os.path.join(tmp_dir, "notes.txt")
            with open(f3_path, "w", encoding="utf-8") as f:
                f.write("Developer scratchpad notes on search engine ranking.")
            repo.upsert_file(
                folder_id=fld_id,
                path=f3_path,
                relative_path="notes.txt",
                filename="notes.txt",
                extension=".txt",
                size_bytes=os.path.getsize(f3_path),
                modified_at="2026-08-30T12:00:00Z",
                file_id="f_notes",
            )
            c3 = ChunkProvenance(
                chunk_id="chk_notes_1",
                file_id="f_notes",
                source_file="notes.txt",
                source_path=f3_path,
                content="Developer scratchpad notes on search engine ranking.",
                h1_parent="Notes",
                section="Notes",
                page=1,
                line_start=1,
                line_end=1,
                char_start=0,
                char_end=52,
            )

            repo.replace_file_chunks("f_arch", [c1])
            repo.replace_file_chunks("f_sec", [c2])
            repo.replace_file_chunks("f_notes", [c3])

            vec_store = SqliteVecStore(conn, dimension=384)
            vec_store.upsert_vectors([
                {"chunk_id": "chk_arch_1", "file_id": "f_arch", "embedding": [0.05] * 384},
                {"chunk_id": "chk_sec_1", "file_id": "f_sec", "embedding": [0.10] * 384},
                {"chunk_id": "chk_notes_1", "file_id": "f_notes", "embedding": [0.15] * 384},
            ])

        yield db, tmp_dir


def test_1_reranker_interface():
    """Test 1: Reranker interface accepts query, candidates list, and top_k, returning structured dicts."""
    reranker = Reranker()
    mock_model = MockCrossEncoderModel(score_mapping={"Doc Alpha": 0.85, "Doc Beta": 0.35})
    reranker._model = mock_model

    candidates = [
        {"chunk_id": "c1", "content": "Doc Alpha", "source_file": "a.txt", "source_path": "/a.txt", "file_id": "f1"},
        {"chunk_id": "c2", "content": "Doc Beta", "source_file": "b.txt", "source_path": "/b.txt", "file_id": "f2"},
    ]

    results = reranker.rerank(query="test query", candidates=candidates, top_k=2)

    assert len(results) == 2
    assert results[0]["chunk_id"] == "c1"
    assert results[0]["rank"] == 1
    assert results[0]["reranker_score"] == round(_sigmoid(0.85), 6)
    assert results[1]["chunk_id"] == "c2"
    assert results[1]["rank"] == 2
    assert results[1]["reranker_score"] == round(_sigmoid(0.35), 6)


def test_2_candidate_count_limiting(phase4_test_setup):
    """Test 2: HybridRetriever respects candidate pool limits for reranking and final top_k."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = mock.MagicMock()
        mock_reranker.rerank.return_value = [
            {"chunk_id": "chk_arch_1", "rank": 1, "score": 0.9, "reranker_score": 0.9}
        ]

        retriever = HybridRetriever(
            db_conn=conn,
            reranker=mock_reranker,
            candidate_pool_size=50,
            rerank_candidate_pool_size=2,
        )

        retriever.search("specifications", top_k=1, mode="hybrid", quality="quality")


        # Verify reranker was called with at most rerank_candidate_pool_size (2) candidates
        call_args = mock_reranker.rerank.call_args
        assert call_args is not None
        passed_candidates = call_args.kwargs.get("candidates") or call_args.args[1]
        assert len(passed_candidates) <= 2
        assert call_args.kwargs.get("top_k") == 1 or call_args.args[2] == 1


def test_3_deterministic_ordering_tie_breaking():
    """Test 3: Tie-breaking is deterministic (reranker_score -> rrf_score -> dense_score -> lexical_score -> chunk_id)."""
    reranker = Reranker()
    mock_model = MockCrossEncoderModel(default_score=0.75)  # Equal reranker score
    reranker._model = mock_model

    candidates = [
        {"chunk_id": "c_gamma", "content": "Text 1", "rrf_score": 0.030, "dense_score": 0.8, "lexical_score": 5.0},
        {"chunk_id": "c_alpha", "content": "Text 2", "rrf_score": 0.030, "dense_score": 0.8, "lexical_score": 5.0},  # Equal scores, chunk_id 'c_alpha' < 'c_gamma'
        {"chunk_id": "c_beta", "content": "Text 3", "rrf_score": 0.035, "dense_score": 0.7, "lexical_score": 4.0},   # Higher RRF score
    ]

    results = reranker.rerank("query", candidates, top_k=3)

    # c_beta has higher RRF (0.035 vs 0.030)
    assert results[0]["chunk_id"] == "c_beta"
    # c_alpha beats c_gamma due to alphabetical chunk_id tie-break
    assert results[1]["chunk_id"] == "c_alpha"
    assert results[2]["chunk_id"] == "c_gamma"


def test_4_reranker_score_field_presence(phase4_test_setup):
    """Test 4: Search response items contain reranker_score float in normal hybrid search."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.912345)

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
        resp = retriever.search("storage engine", top_k=5, mode="hybrid", quality="quality")

        assert resp["total_found"] > 0
        for r in resp["results"]:
            assert "reranker_score" in r
            assert isinstance(r["reranker_score"], float)
            assert r["reranker_score"] == round(_sigmoid(0.912345), 6)


def test_5_existing_scores_preserved(phase4_test_setup):
    """Test 5: Lexical, Dense, and RRF scores are preserved alongside reranker_score."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.88)

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
        resp = retriever.search("storage engine", top_k=5, mode="hybrid", quality="quality")

        first = resp["results"][0]
        assert first["reranker_score"] == round(_sigmoid(0.88), 6)
        assert first["rrf_score"] is not None
        assert isinstance(first["rrf_score"], float)
        # Check evidence scores
        assert (first["lexical_score"] is not None) or (first["dense_score"] is not None)


def test_6_provenance_preserved(phase4_test_setup):
    """Test 6: All chunk provenance attributes survive reranking unchanged."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.95)

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
        resp = retriever.search("Architecture storage", top_k=5, mode="hybrid", quality="quality")

        first = resp["results"][0]
        assert first["chunk_id"] == "chk_arch_1"
        assert first["file_id"] == "f_arch"
        assert first["source_file"] == "arch.md"
        assert "arch.md" in first["source_path"]
        assert first["h1_parent"] == "Architecture"
        assert first["section"] == "Architecture"
        assert first["page"] == 1
        assert first["line_start"] == 1
        assert first["line_end"] == 2
        assert first["char_start"] == 0
        assert first["char_end"] == 65
        assert len(first["snippet"]) > 0


def test_7_and_8_null_score_semantics_preserved(phase4_test_setup):
    """Test 7 & 8: BM25-only candidate preserves dense_score=None; Dense-only preserves lexical_score=None."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        # Create a mock vector store that only returns chk_sec_1, while lexical finds chk_arch_1
        mock_vec = mock.MagicMock()
        mock_vec.search.return_value = [
            {"chunk_id": "chk_sec_1", "file_id": "f_sec", "score": 0.95, "source_file": "sec.pdf", "source_path": "/sec.pdf", "content": "Security"}
        ]
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.7)

        retriever = HybridRetriever(db_conn=conn, vector_store=mock_vec, reranker=mock_reranker)
        resp = retriever.search("storage engine", top_k=10, mode="hybrid", quality="quality")

        found_lex_only = False
        found_dense_only = False

        for r in resp["results"]:
            if r["lexical_rank"] is not None and r["dense_rank"] is None:
                found_lex_only = True
                assert r["dense_score"] is None
                assert isinstance(r["lexical_score"], float)
                assert isinstance(r["reranker_score"], float)
            elif r["lexical_rank"] is None and r["dense_rank"] is not None:
                found_dense_only = True
                assert r["lexical_score"] is None
                assert isinstance(r["dense_score"], float)
                assert isinstance(r["reranker_score"], float)

        assert found_lex_only or found_dense_only


def test_9_and_10_reranker_failure_graceful_fallback(phase4_test_setup):
    """Test 9 & 10: Reranker failure gracefully degrades to RRF ranking with degraded=True and reranker_score=None."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = mock.MagicMock()
        mock_reranker.rerank.side_effect = RuntimeError("Reranker GPU accelerator timeout")

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
        resp = retriever.search("storage engine", top_k=5, mode="hybrid", quality="quality")

        # Must NOT crash!
        assert resp["mode"] == "hybrid"
        assert resp["degraded"] is True
        assert "reranker_unavailable" in resp["degraded_reason"]
        assert resp["total_found"] > 0
        assert resp["retrieval_method"] == "hybrid"

        for r in resp["results"]:
            assert r["reranker_score"] is None
            assert r["rrf_score"] is not None


def test_11_filters_enforced_before_reranking(phase4_test_setup):
    """Test 11: Filters (.pdf only) are strictly enforced before reranker is invoked."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.85)

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
        resp = retriever.search("specifications", top_k=5, filters={"extension": ".pdf"}, mode="hybrid", quality="quality")


        assert resp["total_found"] > 0
        for r in resp["results"]:
            assert r["source_file"].endswith(".pdf")
            assert r["chunk_id"] == "chk_sec_1"


def test_12_empty_candidate_pool_handled_safely(phase4_test_setup):
    """Test 12: An empty candidate pool returns empty results without reranker crash."""
    reranker = Reranker()
    reranker._model = MockCrossEncoderModel()
    assert reranker.rerank("any query", [], top_k=5) == []

    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = mock.MagicMock()
        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)

        # Filter for non-existent extension ensures both lexical and dense candidate pools are empty
        resp = retriever.search("storage engine", top_k=5, filters={"extension": ".nonexistent"}, mode="hybrid", quality="quality")

        assert resp["total_found"] == 0
        assert resp["results"] == []
        mock_reranker.rerank.assert_not_called()


def test_13_top_k_smaller_than_pool(phase4_test_setup):
    """Test 13: top_k smaller than rerank pool returns exactly top_k results."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.8)

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker, rerank_candidate_pool_size=10)
        resp = retriever.search("specifications", top_k=1, mode="hybrid", quality="quality")

        assert resp["total_found"] == 1
        assert len(resp["results"]) == 1


def test_14_top_k_larger_than_available_candidates(phase4_test_setup):
    """Test 14: top_k larger than available candidates returns all available candidates without error."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.8)

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
        resp = retriever.search("specifications", top_k=100, mode="hybrid", quality="quality")

        assert 0 < resp["total_found"] <= 3
        assert len(resp["results"]) == resp["total_found"]


def test_15_duplicate_candidate_ids_deterministic():
    """Test 15: Duplicate candidate chunk_ids are handled deterministically without crashing or nondeterministic reordering."""
    reranker = Reranker()
    mock_model = MockCrossEncoderModel(score_mapping={
        "Content Alpha": 0.85,
        "Content Beta": 0.85,
        "Content Gamma": 0.40,
    })
    reranker._model = mock_model

    # Candidates containing duplicate chunk_ids with equal and different scores
    candidates = [
        {"chunk_id": "chk_dup_1", "content": "Content Alpha", "rrf_score": 0.030, "dense_score": 0.8, "lexical_score": 5.0, "source_file": "doc1.txt"},
        {"chunk_id": "chk_dup_1", "content": "Content Beta", "rrf_score": 0.030, "dense_score": 0.8, "lexical_score": 5.0, "source_file": "doc2.txt"},
        {"chunk_id": "chk_unique_2", "content": "Content Gamma", "rrf_score": 0.020, "dense_score": 0.5, "lexical_score": 2.0, "source_file": "doc3.txt"},
    ]

    # Run multiple times to verify absolute stability across repeated executions
    results_run1 = reranker.rerank(query="search query", candidates=candidates, top_k=3)
    results_run2 = reranker.rerank(query="search query", candidates=candidates, top_k=3)
    results_run3 = reranker.rerank(query="search query", candidates=candidates, top_k=3)

    # 1. No crash and stable result count (3 items returned for top_k=3)
    assert len(results_run1) == 3
    assert len(results_run2) == 3
    assert len(results_run3) == 3

    # 2. Strict deterministic equality across repeated executions
    assert results_run1 == results_run2 == results_run3

    # 3. Correct rank assignment
    assert [r["rank"] for r in results_run1] == [1, 2, 3]

    # 4. Reranker scores are valid and properly assigned
    assert results_run1[0]["reranker_score"] == round(_sigmoid(0.85), 6)
    assert results_run1[1]["reranker_score"] == round(_sigmoid(0.85), 6)
    assert results_run1[2]["reranker_score"] == round(_sigmoid(0.40), 6)
    assert results_run1[2]["chunk_id"] == "chk_unique_2"


def test_16_and_17_model_loaded_once_reused():
    """Test 16 & 17: Reranker model initializes once and fast-path is used without reloads."""
    reranker = Reranker(load_timeout=5.0)
    init_counter = [0]

    def mock_run_init():
        init_counter[0] += 1
        reranker._model = MockCrossEncoderModel(default_score=0.99)
        reranker._init_done.set()

    reranker._run_init = mock_run_init

    # Call 1: triggers init
    res1 = reranker.rerank("q1", [{"chunk_id": "c1", "content": "d1"}])
    assert init_counter[0] == 1
    assert len(res1) == 1

    # Call 2: fast path, init counter remains 1
    res2 = reranker.rerank("q2", [{"chunk_id": "c2", "content": "d2"}])
    assert init_counter[0] == 1
    assert len(res2) == 1


def test_18_latency_stages_measured_independently(phase4_test_setup):
    """Test 18: Latency breakdown contains reranker_inference independently measured."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = Reranker()
        mock_reranker._model = MockCrossEncoderModel(default_score=0.8)

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
        resp = retriever.search("storage engine", top_k=5, mode="hybrid", quality="quality")

        lat = resp["latency_breakdown_ms"]
        assert "normalization" in lat
        assert "lexical_search" in lat
        assert "query_embedding" in lat
        assert "dense_search" in lat
        assert "rrf_fusion" in lat
        assert "reranker_inference" in lat
        assert "total_request" in lat
        assert lat["total_request"] >= lat["reranker_inference"]


def test_19_search_modes_scope(phase4_test_setup):
    """Test 19: BM25-only and Dense-only search modes bypass reranking."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        mock_reranker = mock.MagicMock()

        retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)

        # BM25 mode
        resp_bm25 = retriever.search("storage engine", top_k=5, mode="bm25", quality="fast")
        assert resp_bm25["mode"] == "bm25"
        for r in resp_bm25["results"]:
            assert r["reranker_score"] is None

        # Dense mode
        resp_dense = retriever.search("storage engine", top_k=5, mode="dense", quality="fast")
        assert resp_dense["mode"] == "dense"
        for r in resp_dense["results"]:
            assert r["reranker_score"] is None

        mock_reranker.rerank.assert_not_called()


def test_20_real_cross_encoder_semantic_reordering(phase4_test_setup):
    """Test 20: Real cross-encoder inference (BAAI/bge-reranker-base) reorders candidates semantically."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        # Uses real default_reranker (already cached locally)
        retriever = HybridRetriever(db_conn=conn)
        resp = retriever.search("cryptographic verification and hashing security", top_k=3, mode="hybrid", quality="quality")

        assert resp["total_found"] > 0
        assert resp["degraded"] is False
        # The security document should be ranked #1
        top_doc = resp["results"][0]
        assert top_doc["source_file"] == "sec.pdf"
        assert top_doc["reranker_score"] is not None
        assert isinstance(top_doc["reranker_score"], float)


def test_21_reranker_missing_optional_score_fields():
    """Test 21: Reranker.rerank handles candidates missing optional score fields (rrf_score, dense_score, lexical_score) without KeyError."""
    reranker = Reranker()
    reranker._model = MockCrossEncoderModel(score_mapping={
        "doc A": 0.85,
        "doc B": 0.85,
        "doc C": 0.70,
    })

    # Candidates missing various optional score fields or containing None
    candidates = [
        {"chunk_id": "c1", "content": "doc A"},  # Missing all score fields
        {"chunk_id": "c2", "content": "doc B", "rrf_score": None, "dense_score": None, "lexical_score": None},  # Explicit None
        {"chunk_id": "c3", "content": "doc C", "rrf_score": 0.015, "dense_score": 0.5},  # Missing lexical_score
    ]

    results = reranker.rerank(query="test", candidates=candidates, top_k=3)
    assert len(results) == 3
    # Verify no KeyError occurred and rank is assigned
    assert [r["chunk_id"] for r in results] == ["c1", "c2", "c3"]
    assert all("reranker_score" in r for r in results)


def test_22_complete_candidates_preserve_existing_ordering():
    """Test 22: Complete candidates preserve exact deterministic multi-level tie-breaking ordering."""
    reranker = Reranker()
    # All candidates have identical cross-encoder score -> tie-breaker cascades to rrf -> dense -> lexical -> chunk_id
    reranker._model = MockCrossEncoderModel(default_score=0.90)

    candidates = [
        # Lower rrf_score
        {"chunk_id": "c_low_rrf", "content": "doc 1", "rrf_score": 0.010, "dense_score": 0.9, "lexical_score": 5.0},
        # High rrf_score -> should win tie-break
        {"chunk_id": "c_high_rrf", "content": "doc 2", "rrf_score": 0.030, "dense_score": 0.5, "lexical_score": 2.0},
        # Same rrf_score as c_high_rrf, but lower dense_score
        {"chunk_id": "c_mid_dense", "content": "doc 3", "rrf_score": 0.030, "dense_score": 0.2, "lexical_score": 10.0},
    ]

    results = reranker.rerank(query="test", candidates=candidates, top_k=3)
    assert len(results) == 3
    assert results[0]["chunk_id"] == "c_high_rrf"
    assert results[1]["chunk_id"] == "c_mid_dense"
    assert results[2]["chunk_id"] == "c_low_rrf"


def test_23_expected_unavailability_degrades_gracefully(phase4_test_setup):
    """Test 23: Expected model availability exceptions (RerankerLoadTimeoutError, RuntimeError, OSError, ImportError) degrade to RRF."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        for exc in [
            RerankerLoadTimeoutError("Timed out loading model"),
            RuntimeError("Model file corrupted on disk"),
            OSError("Read error from model cache"),
            ImportError("fastembed not installed"),
            ValueError("Unsupported model identifier"),
        ]:
            mock_reranker = mock.MagicMock()
            mock_reranker.rerank.side_effect = exc

            retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
            resp = retriever.search("storage engine", top_k=5, mode="hybrid", quality="quality")

            assert resp["mode"] == "hybrid"
            assert resp["degraded"] is True
            assert "reranker_unavailable" in resp["degraded_reason"]
            assert str(exc) in resp["degraded_reason"]
            assert resp["total_found"] > 0
            for r in resp["results"]:
                assert r["reranker_score"] is None
                assert r["rrf_score"] is not None


def test_24_unexpected_programming_error_propagates(phase4_test_setup):
    """Test 24: Unexpected programming errors (TypeError, AttributeError, KeyError) are NOT mislabeled as reranker_unavailable and propagate."""
    db, _ = phase4_test_setup
    with db.session() as conn:
        for unexpected_exc in [
            TypeError("search() got an unexpected keyword argument 'bad_kwarg'"),
            AttributeError("'NoneType' object has no attribute 'expected_property'"),
            KeyError("internal_logic_missing_key"),
        ]:
            mock_reranker = mock.MagicMock()
            mock_reranker.rerank.side_effect = unexpected_exc

            retriever = HybridRetriever(db_conn=conn, reranker=mock_reranker)
            with pytest.raises(type(unexpected_exc)):
                retriever.search("storage engine", top_k=5, mode="hybrid", quality="quality")
