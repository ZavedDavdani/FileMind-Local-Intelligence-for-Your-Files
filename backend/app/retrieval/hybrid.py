"""Reciprocal Rank Fusion (RRF) Hybrid Retrieval Engine for Phase 3.

Combines:
- Lexical BM25 (SQLite FTS5)
- Dense Vector Similarity (FastEmbed + sqlite-vec)
- RRF Score Fusion & Deterministic Tie-Breaking
- Authentic Chunk Snippet Generation
- Immutable Provenance Preservation
"""

import json
import logging
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from app.retrieval.embeddings import EmbeddingEngine, default_embedding_engine
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.normalizer import NormalizedQuery, normalize_query
from app.retrieval.vector_store import BaseVectorStore, SqliteVecStore

logger = logging.getLogger("FileMind.Retrieval.Hybrid")

DEFAULT_RRF_K = 60
DEFAULT_CANDIDATE_POOL = 50


def generate_real_snippet(content: str, query_tokens: List[str], max_chars: int = 240) -> str:
    """
    Generates an authentic snippet from actual chunk content, centered around matching query terms.
    Does not fabricate or modify source words.
    """
    if not content:
        return ""

    cleaned_content = content.replace("\n", " ").strip()
    if len(cleaned_content) <= max_chars:
        return cleaned_content

    if not query_tokens:
        return cleaned_content[:max_chars].strip() + "..."

    # Find earliest match of any query token
    content_lower = cleaned_content.lower()
    best_pos = -1

    for tok in query_tokens:
        if len(tok) < 2:
            continue
        pos = content_lower.find(tok.lower())
        if pos != -1:
            if best_pos == -1 or pos < best_pos:
                best_pos = pos

    if best_pos == -1:
        # Fall back to start
        return cleaned_content[:max_chars].strip() + "..."

    # Window around best match
    half_window = max_chars // 2
    start_idx = max(0, best_pos - half_window)
    end_idx = min(len(cleaned_content), start_idx + max_chars)

    # Adjust window if at the end
    if end_idx - start_idx < max_chars:
        start_idx = max(0, end_idx - max_chars)

    snippet = cleaned_content[start_idx:end_idx].strip()
    prefix = "..." if start_idx > 0 else ""
    suffix = "..." if end_idx < len(cleaned_content) else ""
    return f"{prefix}{snippet}{suffix}"


class HybridRetriever:
    """Combines lexical and dense retrieval using Reciprocal Rank Fusion (RRF)."""

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        embedding_engine: Optional[EmbeddingEngine] = None,
        vector_store: Optional[BaseVectorStore] = None,
        rrf_k: int = DEFAULT_RRF_K,
        candidate_pool_size: int = DEFAULT_CANDIDATE_POOL,
    ):
        self.conn = db_conn
        self.embedding_engine = embedding_engine or default_embedding_engine
        self.vector_store = vector_store or SqliteVecStore(
            db_conn, dimension=self.embedding_engine.dimension
        )
        self.lexical_retriever = LexicalRetriever(db_conn)
        self.rrf_k = rrf_k
        self.candidate_pool_size = candidate_pool_size

    def search(
        self,
        query: Union[str, NormalizedQuery],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        mode: str = "hybrid",  # "hybrid", "bm25", "dense"
    ) -> Dict[str, Any]:
        """
        Executes hybrid, BM25-only, or dense-only retrieval with explicit timing breakdown.
        
        Returns:
        {
            "query": "...",
            "mode": "hybrid|bm25|dense",
            "total_found": int,
            "latency_breakdown_ms": {
                "normalization": float,
                "lexical_search": float,
                "query_embedding": float,
                "dense_search": float,
                "rrf_fusion": float,
                "total_request": float
            },
            "results": [...]
        }
        """
        t_request_start = time.perf_counter()
        latencies = {
            "normalization": 0.0,
            "lexical_search": 0.0,
            "query_embedding": 0.0,
            "dense_search": 0.0,
            "rrf_fusion": 0.0,
            "total_request": 0.0,
        }

        # Stage A: Query Normalization
        t0 = time.perf_counter()
        if isinstance(query, str):
            norm_q = normalize_query(query)
        else:
            norm_q = query
        latencies["normalization"] = round((time.perf_counter() - t0) * 1000.0, 3)

        if norm_q.is_empty:
            latencies["total_request"] = round((time.perf_counter() - t_request_start) * 1000.0, 3)
            return {
                "query": norm_q.raw_query,
                "mode": mode,
                "total_found": 0,
                "latency_breakdown_ms": latencies,
                "results": [],
            }

        lexical_candidates: List[Dict[str, Any]] = []
        dense_candidates: List[Dict[str, Any]] = []

        # Stage B: BM25 Lexical Retrieval
        if mode in ("hybrid", "bm25"):
            t0 = time.perf_counter()
            lexical_candidates = self.lexical_retriever.search(
                norm_q,
                top_k=self.candidate_pool_size if mode == "hybrid" else top_k,
                filters=filters,
            )
            latencies["lexical_search"] = round((time.perf_counter() - t0) * 1000.0, 3)

        # Stage C & D: Dense Retrieval (Query Embedding + Vector Search)
        degraded = False
        degraded_reason = None

        if mode in ("hybrid", "dense"):
            try:
                t0 = time.perf_counter()
                q_vector = self.embedding_engine.embed_query(norm_q.normalized_query)
                latencies["query_embedding"] = round((time.perf_counter() - t0) * 1000.0, 3)

                t0 = time.perf_counter()
                dense_candidates = self.vector_store.search(
                    q_vector,
                    top_k=self.candidate_pool_size if mode == "hybrid" else top_k,
                    filters=filters,
                )
                latencies["dense_search"] = round((time.perf_counter() - t0) * 1000.0, 3)
            except Exception as dense_exc:
                if mode == "dense":
                    raise
                logger.warning(
                    "Dense retrieval unavailable during hybrid search; degrading to BM25 fallback: %s",
                    str(dense_exc),
                )
                degraded = True
                degraded_reason = f"dense_retrieval_unavailable: {str(dense_exc)}"
                dense_candidates = []

        # Stage E: Fusion & Ranking
        t0 = time.perf_counter()
        final_results: List[Dict[str, Any]] = []

        if mode == "bm25":
            for rank, r in enumerate(lexical_candidates[:top_k], start=1):
                r_copy = dict(r)
                r_copy["rank"] = rank
                r_copy["snippet"] = generate_real_snippet(r_copy["content"], norm_q.tokens)
                final_results.append(r_copy)

        elif mode == "dense":
            for rank, r in enumerate(dense_candidates[:top_k], start=1):
                r_copy = dict(r)
                r_copy["rank"] = rank
                r_copy["snippet"] = generate_real_snippet(r_copy["content"], norm_q.tokens)
                final_results.append(r_copy)

        elif degraded:
            # Degraded Hybrid: Direct BM25 Fallback without fabricating dense scores
            for rank, r in enumerate(lexical_candidates[:top_k], start=1):
                snippet = generate_real_snippet(r["content"], norm_q.tokens)
                final_results.append({
                    "rank": rank,
                    "chunk_id": r["chunk_id"],
                    "file_id": r["file_id"],
                    "score": r["score"],
                    "rrf_score": None,
                    "lexical_score": r["score"],
                    "dense_score": None,
                    "lexical_rank": rank,
                    "dense_rank": None,
                    "retrieval_method": "bm25_fallback",
                    "source_file": r["source_file"],
                    "source_path": r["source_path"],
                    "page": r.get("page"),
                    "section": r.get("section"),
                    "h1_parent": r.get("h1_parent"),
                    "h2_parent": r.get("h2_parent"),
                    "line_start": r.get("line_start"),
                    "line_end": r.get("line_end"),
                    "char_start": r.get("char_start"),
                    "char_end": r.get("char_end"),
                    "snippet": snippet,
                    "content": r["content"],
                    "content_hash": r["content_hash"],
                    "metadata": r.get("metadata", {}),
                })

        else:  # Hybrid RRF
            # Map candidate chunk_ids to their ranks and scores
            lex_ranks = {r["chunk_id"]: (rank, r) for rank, r in enumerate(lexical_candidates, start=1)}
            dense_ranks = {r["chunk_id"]: (rank, r) for rank, r in enumerate(dense_candidates, start=1)}

            all_chunk_ids = set(lex_ranks.keys()).union(set(dense_ranks.keys()))
            scored_candidates = []

            for cid in all_chunk_ids:
                lex_rank, lex_item = lex_ranks.get(cid, (None, None))
                dense_rank, dense_item = dense_ranks.get(cid, (None, None))

                # RRF calculation
                rrf_score = 0.0
                if lex_rank is not None:
                    rrf_score += 1.0 / (self.rrf_k + lex_rank)
                if dense_rank is not None:
                    rrf_score += 1.0 / (self.rrf_k + dense_rank)

                base_item = lex_item or dense_item
                lex_score = lex_item["score"] if lex_item else None
                dense_score = dense_item["score"] if dense_item else None

                scored_candidates.append({
                    "chunk_id": cid,
                    "rrf_score": round(rrf_score, 6),
                    "lexical_score": lex_score,
                    "dense_score": dense_score,
                    "lexical_rank": lex_rank,
                    "dense_rank": dense_rank,
                    "item": base_item,
                })

            # Deterministic ordering: rrf_score DESC -> dense_score DESC -> lexical_score DESC -> chunk_id ASC
            scored_candidates.sort(
                key=lambda x: (
                    -x["rrf_score"],
                    -(x["dense_score"] if x["dense_score"] is not None else 0.0),
                    -(x["lexical_score"] if x["lexical_score"] is not None else 0.0),
                    x["chunk_id"],
                )
            )

            for rank, cand in enumerate(scored_candidates[:top_k], start=1):
                item = cand["item"]
                snippet = generate_real_snippet(item["content"], norm_q.tokens)
                final_results.append({
                    "rank": rank,
                    "chunk_id": item["chunk_id"],
                    "file_id": item["file_id"],
                    "score": cand["rrf_score"],
                    "rrf_score": cand["rrf_score"],
                    "lexical_score": cand["lexical_score"],
                    "dense_score": cand["dense_score"],
                    "lexical_rank": cand["lexical_rank"],
                    "dense_rank": cand["dense_rank"],
                    "retrieval_method": "hybrid",
                    "source_file": item["source_file"],
                    "source_path": item["source_path"],
                    "page": item.get("page"),
                    "section": item.get("section"),
                    "h1_parent": item.get("h1_parent"),
                    "h2_parent": item.get("h2_parent"),
                    "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"),
                    "char_start": item.get("char_start"),
                    "char_end": item.get("char_end"),
                    "snippet": snippet,
                    "content": item["content"],
                    "content_hash": item["content_hash"],
                    "metadata": item.get("metadata", {}),
                })

        latencies["rrf_fusion"] = round((time.perf_counter() - t0) * 1000.0, 3)
        latencies["total_request"] = round((time.perf_counter() - t_request_start) * 1000.0, 3)

        return {
            "query": norm_q.raw_query,
            "mode": mode,
            "total_found": len(final_results),
            "latency_breakdown_ms": latencies,
            "results": final_results,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "retrieval_method": "bm25_fallback" if degraded else mode,
        }
