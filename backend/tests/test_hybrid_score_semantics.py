"""Regression test verifying exact null score semantics for absent hybrid candidates."""

import os
import sys
import tempfile
import sqlite3
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_store import SqliteVecStore
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


def test_hybrid_absent_candidate_scores_are_none():
    """Verifies that non-candidate items in hybrid search have None (null) scores instead of 0.0."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_scores.db")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    engine = EmbeddingEngine("sentence-transformers/all-MiniLM-L6-v2")
    texts = [c["content"] for c in meta["chunks"]]
    vectors = engine.embed_texts(texts, batch_size=16)

    chunk_records = [
        {"chunk_id": c["chunk_id"], "file_id": c["file_id"], "embedding": vec}
        for c, vec in zip(meta["chunks"], vectors)
    ]

    with db.session() as conn:
        vec_store = SqliteVecStore(conn, dimension=engine.dimension)
        vec_store.upsert_vectors(chunk_records)

        retriever = HybridRetriever(
            db_conn=conn,
            embedding_engine=engine,
            vector_store=vec_store,
            candidate_pool_size=10,
        )

        # 1. Search for a query that has strong BM25 and dense results
        res = retriever.search("sample_system_spec.pdf", top_k=10, mode="hybrid")
        assert res["total_found"] > 0

        for r in res["results"]:
            # If retrieved in both, both scores are float
            if r["lexical_rank"] is not None and r["dense_rank"] is not None:
                assert isinstance(r["lexical_score"], float)
                assert isinstance(r["dense_score"], float)
                assert r["lexical_score"] > 0
                assert r["dense_score"] > 0
            # If only in lexical, dense_score must be None
            elif r["lexical_rank"] is not None and r["dense_rank"] is None:
                assert isinstance(r["lexical_score"], float)
                assert r["dense_score"] is None
                assert r["dense_rank"] is None
            # If only in dense, lexical_score must be None
            elif r["lexical_rank"] is None and r["dense_rank"] is not None:
                assert r["lexical_score"] is None
                assert r["lexical_rank"] is None
                assert isinstance(r["dense_score"], float)

        # 2. Search BM25-only mode
        res_bm25 = retriever.search("sample_system_spec.pdf", top_k=5, mode="bm25")
        for r in res_bm25["results"]:
            assert r["score"] > 0
            assert "dense_score" not in r or r.get("dense_score") is None

        # 3. Search Dense-only mode
        res_dense = retriever.search("deterministic document retrieval", top_k=5, mode="dense")
        for r in res_dense["results"]:
            assert r["score"] > 0
