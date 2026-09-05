"""Reciprocal Rank Fusion (RRF) Hybrid Retrieval Engine for .

Combines:
- Lexical BM25 (SQLite FTS5)
- Dense Vector Similarity (FastEmbed + sqlite-vec)
- RRF Score Fusion & Deterministic Tie-Breaking
- Authentic Chunk Snippet Generation
- Immutable Provenance Preservation
"""

import collections
import copy
import json
import logging
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from app.core.config import DEFAULT_RERANK_POOL
from app.retrieval.embeddings import EmbeddingEngine, default_embedding_engine
from app.retrieval.lexical import LexicalRetriever, compute_filename_match_boost, extract_filename_stems
from app.retrieval.normalizer import NormalizedQuery, normalize_query
from app.retrieval.reranker import Reranker, RerankerLoadTimeoutError, default_reranker
from app.retrieval.vector_store import BaseVectorStore, SqliteVecStore

logger = logging.getLogger("FileMind.Retrieval.Hybrid")

DEFAULT_RRF_K = 60
DEFAULT_CANDIDATE_POOL = 50


class QueryCache:
    """Thread-safe LRU cache for search results with authoritative mutation invalidation."""

    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self._cache: collections.OrderedDict[str, Dict[str, Any]] = collections.OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return copy.deepcopy(self._cache[key])
            return None

    def put(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = copy.deepcopy(value)
            if len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)


global_query_cache = QueryCache()


def invalidate_query_cache() -> None:
    """Authoritatively clears the global search query cache upon data mutations."""
    global_query_cache.invalidate()


def _get_db_identifier(conn: sqlite3.Connection) -> str:
    """Returns a unique identifier for the database connection (path or in-memory id)."""
    try:
        cur = conn.execute("PRAGMA database_list;")
        rows = cur.fetchall()
        for row in rows:
            f = row[2] if (isinstance(row, (tuple, list)) and len(row) > 2) else (row["file"] if isinstance(row, sqlite3.Row) else "")
            if f:
                return str(f)
        return f"mem_{id(conn)}"
    except Exception:
        return f"conn_{id(conn)}"

COMMON_FILE_EXTENSIONS = {
    "pdf", "docx", "pptx", "xlsx", "csv", "md", "py", "json", "txt",
    "ts", "tsx", "js", "jsx", "html", "css", "rs", "go", "c", "cpp",
    "h", "java", "sh", "bat", "cmd", "sql", "yaml", "yml", "toml",
    "xml", "log", "env", "ini", "cfg", "zip", "tar", "gz", "7z",
    "png", "jpg", "jpeg", "gif", "svg", "rtf", "odt", "ods", "odp",
}


def extract_explicit_filename_intent(query_str: Optional[str]) -> Optional[str]:
    """
    Detects whether a query is explicitly targeting a specific filename or path.
    Returns the normalized filename if detected, or None for normal natural-language queries.

    Examples:
    - 'nonexistent_report.pdf' -> 'nonexistent_report.pdf'
    - ' "budget_2024.xlsx" ' -> 'budget_2024.xlsx'
    - 'subfolder/notes.md' -> 'notes.md'
    - 'subfolder\\notes.md' -> 'notes.md'
    - 'How does semantic retrieval work?' -> None
    - 'What is in report.pdf?' -> None (natural-language conversational question)
    - 'def get_config():' -> None
    """
    if not query_str:
        return None
    raw = query_str.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()

    if not raw or "?" in raw or "\n" in raw:
        return None

    clean_path = raw.replace("\\", "/").strip()
    filename = clean_path.split("/")[-1].strip()

    if "." not in filename:
        return None

    parts = filename.rsplit(".", 1)
    name_part, ext_part = parts[0].strip(), parts[1].lower().strip()

    if not ext_part or ext_part not in COMMON_FILE_EXTENSIONS:
        return None

    if not name_part:
        return None

    conversational_starters = {
        "what", "how", "why", "who", "where", "when", "can", "could", "would",
        "is", "are", "tell", "summarize", "find", "search", "explain", "describe",
        "show", "give", "list"
    }
    words = name_part.lower().split()
    if len(words) > 1 and words[0] in conversational_starters:
        return None

    if len(words) > 6:
        return None

    return filename



def generate_real_snippet(content: str, query_tokens: List[str], max_chars: int = 240) -> str:
    """
    Generates an authentic snippet from actual chunk content, centered around matching query terms.
    Prefers word/token boundary matches over interior substrings to avoid false anchors
    (e.g., 'cat' matching inside 'category').
    Does not fabricate or modify source words.
    """
    if not content:
        return ""

    cleaned_content = content.replace("\n", " ").strip()
    if len(cleaned_content) <= max_chars:
        return cleaned_content

    if not query_tokens:
        return cleaned_content[:max_chars].strip() + "..."

    valid_tokens = [tok for tok in query_tokens if len(tok) >= 2]
    if not valid_tokens:
        return cleaned_content[:max_chars].strip() + "..."

    best_pos = -1

    # Pass 1: Single compiled alternation pattern for word/token boundaries
    escaped_tokens = "|".join(re.escape(tok) for tok in sorted(valid_tokens, key=len, reverse=True))
    try:
        pattern = re.compile(rf"(?<![a-zA-Z0-9])(?:{escaped_tokens})(?![a-zA-Z0-9])", re.IGNORECASE)
        m = pattern.search(cleaned_content)
        if m:
            best_pos = m.start()
    except Exception:
        pass

    # Pass 2: If no boundary match found, fall back to standard substring search
    if best_pos == -1:
        content_lower = cleaned_content.lower()
        for tok in valid_tokens:
            pos = content_lower.find(tok.lower())
            if pos != -1:
                if best_pos == -1 or pos < best_pos:
                    best_pos = pos

    # Pass 3: If still no match, fall back to start of content
    if best_pos == -1:
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


_DEFAULT_RERANKER = object()


class HybridRetriever:
    """Combines lexical and dense retrieval using Reciprocal Rank Fusion (RRF)."""

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        embedding_engine: Optional[EmbeddingEngine] = None,
        vector_store: Optional[BaseVectorStore] = None,
        reranker: Any = _DEFAULT_RERANKER,
        rrf_k: int = DEFAULT_RRF_K,
        candidate_pool_size: int = DEFAULT_CANDIDATE_POOL,
        rerank_candidate_pool_size: int = DEFAULT_RERANK_POOL,
    ):
        self.conn = db_conn
        self.embedding_engine = embedding_engine or default_embedding_engine
        self.vector_store = vector_store or SqliteVecStore(
            db_conn, dimension=self.embedding_engine.dimension
        )
        self.lexical_retriever = LexicalRetriever(db_conn)
        self.reranker = default_reranker if reranker is _DEFAULT_RERANKER else reranker
        self.rrf_k = rrf_k
        self.candidate_pool_size = candidate_pool_size
        self.rerank_candidate_pool_size = rerank_candidate_pool_size

    @classmethod
    def invalidate_cache(cls) -> None:
        """Invalidates global query search cache."""
        global_query_cache.invalidate()

    @staticmethod
    def _build_result_dict(
        item: Dict[str, Any],
        rank: int,
        query_tokens: List[str],
        retrieval_method: str,
        score: Optional[float] = None,
        reranker_score: Optional[float] = None,
        rrf_score: Optional[float] = None,
        lexical_score: Optional[float] = None,
        dense_score: Optional[float] = None,
        lexical_rank: Optional[int] = None,
        dense_rank: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Constructs a unified candidate result dictionary ensuring complete metadata coverage."""
        content = item.get("content", "")
        snippet = generate_real_snippet(content, query_tokens)
        meta = item.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}

        return {
            "rank": rank,
            "chunk_id": item.get("chunk_id", ""),
            "file_id": item.get("file_id", ""),
            "score": score if score is not None else item.get("score"),
            "reranker_score": reranker_score,
            "rrf_score": rrf_score,
            "lexical_score": lexical_score,
            "dense_score": dense_score,
            "lexical_rank": lexical_rank,
            "dense_rank": dense_rank,
            "retrieval_method": retrieval_method,
            "source_file": item.get("source_file", ""),
            "source_path": item.get("source_path", ""),
            "page": item.get("page"),
            "section": item.get("section"),
            "h1_parent": item.get("h1_parent"),
            "h2_parent": item.get("h2_parent"),
            "line_start": item.get("line_start"),
            "line_end": item.get("line_end"),
            "char_start": item.get("char_start"),
            "char_end": item.get("char_end"),
            "sheet_name": item.get("sheet_name") or meta.get("sheet_name"),
            "slide_number": item.get("slide_number") or meta.get("slide_number"),
            "time_start": item.get("time_start") or meta.get("time_start"),
            "time_end": item.get("time_end") or meta.get("time_end"),
            "frame_index": item.get("frame_index") or meta.get("frame_index"),
            "media_type": item.get("media_type") or meta.get("media_type") or "document",
            "extraction_method": item.get("extraction_method") or meta.get("extraction_method"),
            "snippet": snippet,
            "content": content,
            "content_hash": item.get("content_hash", ""),
            "metadata": meta,
        }

    def search(
        self,
        query: Union[str, NormalizedQuery],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        mode: str = "hybrid",  # "hybrid", "bm25", "dense"
        quality: str = "fast",  # "fast", "quality"
    ) -> Dict[str, Any]:
        """
        Executes Fast or Quality retrieval across hybrid, BM25-only, or dense-only modes
        with explicit timing breakdown and provenance.
        """
        t_request_start = time.perf_counter()
        latencies = {
            "normalization": 0.0,
            "lexical_search": 0.0,
            "query_embedding": 0.0,
            "dense_search": 0.0,
            "rrf_fusion": 0.0,
            "reranker_inference": 0.0,
            "total_request": 0.0,
        }

        mode = (mode or "hybrid").lower().strip()
        quality = (quality or "fast").lower().strip()

        if mode not in ("hybrid", "bm25", "dense"):
            raise ValueError(f"Invalid retrieval mode: '{mode}'. Valid options are 'hybrid', 'bm25', 'dense'.")
        if quality not in ("fast", "quality"):
            raise ValueError(f"Invalid quality mode: '{quality}'. Valid options are 'fast', 'quality'.")
        if quality == "quality" and mode != "hybrid":
            raise ValueError(f"Quality mode is only supported with hybrid retrieval (received mode='{mode}', quality='{quality}').")

        # Cache check
        cache_key = None
        try:
            db_id = _get_db_identifier(self.conn)
            vs_id = id(self.vector_store)
            rr_id = id(self.reranker)
            filter_str = json.dumps(filters, sort_keys=True) if filters else ""
            raw_q = query if isinstance(query, str) else (query.raw_query if hasattr(query, "raw_query") else str(query))
            cache_key = f"{db_id}||{vs_id}||{rr_id}||{raw_q.strip()}||{top_k}||{mode}||{quality}||{filter_str}"
        except Exception:
            cache_key = None

        if cache_key:
            cached_res = global_query_cache.get(cache_key)
            if cached_res is not None:
                cached_res["latency_breakdown_ms"]["total_request"] = round(
                    (time.perf_counter() - t_request_start) * 1000.0, 3
                )
                return cached_res

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
                "quality": quality,
                "total_found": 0,
                "latency_breakdown_ms": latencies,
                "results": [],
                "degraded": False,
                "degraded_reason": None,
                "retrieval_method": mode,
                "explicit_filename_intent": None,
            }

        # Stage A.1: Explicit Filename Intent Handling
        effective_filters = dict(filters) if filters else {}
        filename_intent = extract_explicit_filename_intent(norm_q.raw_query)
        if filename_intent:
            fn_lower = filename_intent.lower()
            raw_path_lower = norm_q.raw_query.strip().strip('"\'').replace("\\", "/").lower()
            where_fn = "(LOWER(f.filename) = ? OR LOWER(f.path) = ? OR LOWER(f.relative_path) = ?)"
            fn_params = [fn_lower, raw_path_lower, raw_path_lower]
            if effective_filters.get("folder_id"):
                where_fn += " AND f.folder_id = ?"
                fn_params.append(effective_filters["folder_id"])
            if effective_filters.get("extension"):
                ext = effective_filters["extension"].lower()
                if not ext.startswith("."):
                    ext = f".{ext}"
                where_fn += " AND LOWER(f.extension) = ?"
                fn_params.append(ext)

            cursor = self.conn.execute(
                f"""
                SELECT f.file_id, f.filename, f.path, f.relative_path
                FROM files f
                WHERE {where_fn} AND f.index_status != 'MISSING';
                """,
                fn_params,
            )
            matched_files = cursor.fetchall()
            if not matched_files:
                # Explicit filename lookup for a file not present in indexed corpus.
                # Must return consistent not-found state across BM25, Dense, Hybrid Fast and Quality.
                latencies["total_request"] = round((time.perf_counter() - t_request_start) * 1000.0, 3)
                return {
                    "query": norm_q.raw_query,
                    "mode": mode,
                    "quality": quality,
                    "total_found": 0,
                    "latency_breakdown_ms": latencies,
                    "results": [],
                    "degraded": False,
                    "degraded_reason": None,
                    "retrieval_method": mode,
                    "explicit_filename_intent": filename_intent,
                }
            elif not effective_filters.get("file_id") and not effective_filters.get("file_ids") and matched_files:
                # If explicit filename matches indexed files, scope retrieval across all modes
                matched_fids = [
                    r[0] if isinstance(r, (tuple, list)) else r["file_id"] for r in matched_files
                ]
                if len(matched_fids) == 1:
                    effective_filters["file_id"] = matched_fids[0]
                else:
                    effective_filters["file_ids"] = matched_fids

        lexical_candidates: List[Dict[str, Any]] = []
        dense_candidates: List[Dict[str, Any]] = []

        # Candidate pool for underlying retrieval
        arm_pool_size = max(self.candidate_pool_size, top_k * 2, 50) if mode == "hybrid" else top_k

        # Stage B: BM25 Lexical Retrieval
        lex_error = None
        if mode in ("hybrid", "bm25"):
            t0 = time.perf_counter()
            try:
                lexical_candidates = self.lexical_retriever.search(
                    norm_q,
                    top_k=arm_pool_size,
                    filters=effective_filters,
                )
            except Exception as lex_exc:
                if mode == "bm25":
                    raise
                logger.warning(
                    "Lexical retrieval unavailable during hybrid search; evaluating fallback: %s",
                    str(lex_exc),
                )
                lex_error = lex_exc
                lexical_candidates = []
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
                raw_dense = self.vector_store.search(
                    q_vector,
                    top_k=arm_pool_size,
                    filters=effective_filters,
                )
                latencies["dense_search"] = round((time.perf_counter() - t0) * 1000.0, 3)

                valid_cands = []
                for cand in (raw_dense or []):
                    if isinstance(cand, dict) and cand.get("chunk_id") is not None and "score" in cand:
                        valid_cands.append(dict(cand))
                    else:
                        logger.warning("Dropping malformed dense candidate: %s", cand)

                # Batch hydrate candidate metadata in a single query if needed
                missing_cids = [
                    c["chunk_id"] for c in valid_cands
                    if "content" not in c or "source_file" not in c or not c.get("source_file")
                ]
                chunk_details = {}
                if missing_cids:
                    placeholders = ",".join("?" for _ in missing_cids)
                    cur = self.conn.execute(
                        f"""
                        SELECT chunk_id, source_file, source_path, page, section, h1_parent, h2_parent,
                               line_start, line_end, char_start, char_end, content, content_hash, metadata_json
                        FROM chunks WHERE chunk_id IN ({placeholders});
                        """,
                        missing_cids,
                    )
                    rows = cur.fetchall()
                    col_names = [d[0] for d in cur.description] if cur.description else []
                    for row in rows:
                        row_dict = dict(row) if isinstance(row, sqlite3.Row) else {col_names[i]: row[i] for i in range(len(col_names))}
                        chunk_details[row_dict["chunk_id"]] = row_dict

                dense_candidates = []
                for cand_dict in valid_cands:
                    cid = cand_dict["chunk_id"]
                    if cid in chunk_details:
                        row_dict = chunk_details[cid]
                        for k, v in row_dict.items():
                            if k == "metadata_json":
                                if "metadata" not in cand_dict:
                                    try:
                                        cand_dict["metadata"] = json.loads(v or "{}")
                                    except Exception:
                                        cand_dict["metadata"] = {}
                            elif k not in cand_dict or cand_dict[k] is None:
                                cand_dict[k] = v
                    dense_candidates.append(cand_dict)
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

        if lex_error is not None:
            if degraded:
                # Both lexical and dense failed
                raise RuntimeError(
                    f"Both lexical and dense retrieval failed during hybrid search: "
                    f"lexical={lex_error}, dense={degraded_reason}"
                )
            # Lexical failed, but dense succeeded -> graceful degradation to dense fallback
            degraded = True
            degraded_reason = f"lexical_retrieval_unavailable: {str(lex_error)}"

        # Ensure deterministic candidate sorting with chunk_id tie-breaker
        if lexical_candidates:
            lexical_candidates.sort(key=lambda x: (-(x.get("score") or 0.0), str(x.get("chunk_id", ""))))
        if dense_candidates:
            dense_candidates.sort(key=lambda x: (-(x.get("score") or 0.0), str(x.get("chunk_id", ""))))

        # Stage E: Fusion & Ranking
        t0 = time.perf_counter()
        final_results: List[Dict[str, Any]] = []

        if mode == "bm25":
            for rank, r in enumerate(lexical_candidates[:top_k], start=1):
                final_results.append(
                    self._build_result_dict(
                        item=r,
                        rank=rank,
                        query_tokens=norm_q.tokens,
                        retrieval_method="bm25",
                        score=r.get("score"),
                        lexical_score=r.get("score"),
                        lexical_rank=rank,
                    )
                )

        elif mode == "dense":
            for rank, r in enumerate(dense_candidates[:top_k], start=1):
                final_results.append(
                    self._build_result_dict(
                        item=r,
                        rank=rank,
                        query_tokens=norm_q.tokens,
                        retrieval_method="dense",
                        score=r.get("score"),
                        dense_score=r.get("score"),
                        dense_rank=rank,
                    )
                )

        elif degraded:
            if "lexical_retrieval_unavailable" in (degraded_reason or ""):
                # Degraded Hybrid: Direct Dense Fallback without fabricating lexical scores
                for rank, r in enumerate(dense_candidates[:top_k], start=1):
                    final_results.append(
                        self._build_result_dict(
                            item=r,
                            rank=rank,
                            query_tokens=norm_q.tokens,
                            retrieval_method="dense_fallback",
                            score=r.get("score"),
                            dense_score=r.get("score"),
                            dense_rank=rank,
                        )
                    )
            else:
                # Degraded Hybrid: Direct BM25 Fallback without fabricating dense scores
                for rank, r in enumerate(lexical_candidates[:top_k], start=1):
                    final_results.append(
                        self._build_result_dict(
                            item=r,
                            rank=rank,
                            query_tokens=norm_q.tokens,
                            retrieval_method="bm25_fallback",
                            score=r.get("score"),
                            lexical_score=r.get("score"),
                            lexical_rank=rank,
                        )
                    )

        else:  # Hybrid Mode (BM25 + Dense both succeeded)
            # Map candidate chunk_ids to their ranks and scores
            lex_ranks = {r["chunk_id"]: (rank, r) for rank, r in enumerate(lexical_candidates, start=1)}
            dense_ranks = {r["chunk_id"]: (rank, r) for rank, r in enumerate(dense_candidates, start=1)}

            all_chunk_ids = set(lex_ranks.keys()).union(set(dense_ranks.keys()))
            scored_candidates = []
            q_raw_lower = (norm_q.raw_query or "").lower().strip()

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

                # Exact filename and stem boost for RRF priority
                sf = (base_item.get("source_file") or "").lower()
                base_rrf_boost = compute_filename_match_boost(q_raw_lower, norm_q.tokens, sf, domain="rrf")
                if base_rrf_boost >= 0.0200:
                    if lex_rank is not None and lex_rank <= 3:
                        rrf_score += 0.0200
                    else:
                        rrf_score += 0.0050
                elif base_rrf_boost > 0.0:
                    rrf_score += base_rrf_boost

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

            latencies["rrf_fusion"] = round((time.perf_counter() - t0) * 1000.0, 3)

            # Quality Pipeline vs Fast Pipeline
            if quality == "fast":
                # Fast mode: Return RRF results directly without Cross-Encoder reranking
                for rank, cand in enumerate(scored_candidates[:top_k], start=1):
                    final_results.append(
                        self._build_result_dict(
                            item=cand["item"],
                            rank=rank,
                            query_tokens=norm_q.tokens,
                            retrieval_method="hybrid",
                            score=cand["rrf_score"],
                            rrf_score=cand["rrf_score"],
                            lexical_score=cand["lexical_score"],
                            dense_score=cand["dense_score"],
                            lexical_rank=cand["lexical_rank"],
                            dense_rank=cand["dense_rank"],
                        )
                    )
                latencies["reranker_inference"] = 0.0

            else:
                # Quality mode: Cross-Encoder Reranking
                # Candidate pool policy: Dynamic expansion to max(pool_size, top_k) capped at safe ceiling 100
                effective_rerank_pool = min(max(self.rerank_candidate_pool_size, top_k), 100)
                candidates_to_rerank = scored_candidates[:effective_rerank_pool]
                pre_rerank_items: List[Dict[str, Any]] = []

                for rank, cand in enumerate(candidates_to_rerank, start=1):
                    pre_rerank_items.append(
                        self._build_result_dict(
                            item=cand["item"],
                            rank=rank,
                            query_tokens=norm_q.tokens,
                            retrieval_method="hybrid",
                            score=cand["rrf_score"],
                            rrf_score=cand["rrf_score"],
                            lexical_score=cand["lexical_score"],
                            dense_score=cand["dense_score"],
                            lexical_rank=cand["lexical_rank"],
                            dense_rank=cand["dense_rank"],
                        )
                    )

                if pre_rerank_items and self.reranker is not None:
                    t_rerank = time.perf_counter()
                    try:
                        final_results = self.reranker.rerank(
                            query=norm_q.raw_query,
                            candidates=pre_rerank_items,
                            top_k=top_k,
                        )
                        latencies["reranker_inference"] = round((time.perf_counter() - t_rerank) * 1000.0, 3)
                    except (RerankerLoadTimeoutError, RuntimeError, OSError, ImportError, ValueError) as rerank_exc:
                        logger.warning(
                            "Reranker unavailable during quality hybrid search; degrading to RRF ranking: %s",
                            str(rerank_exc),
                        )
                        degraded = True
                        degraded_reason = f"reranker_unavailable: {str(rerank_exc)}"
                        latencies["reranker_inference"] = round((time.perf_counter() - t_rerank) * 1000.0, 3)
                        final_results = pre_rerank_items[:top_k]
                else:
                    degraded = True
                    degraded_reason = "reranker_unavailable: reranker not configured"
                    final_results = pre_rerank_items[:top_k]

        latencies["total_request"] = round((time.perf_counter() - t_request_start) * 1000.0, 3)

        if degraded:
            if "lexical_retrieval_unavailable" in (degraded_reason or ""):
                retrieval_method = "dense_fallback"
            elif "dense_retrieval_unavailable" in (degraded_reason or ""):
                retrieval_method = "bm25_fallback"
            else:
                retrieval_method = "hybrid"
        else:
            retrieval_method = mode

        res_dict = {
            "query": norm_q.raw_query,
            "mode": mode,
            "quality": quality,
            "total_found": len(final_results),
            "latency_breakdown_ms": latencies,
            "results": final_results,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "retrieval_method": retrieval_method,
            "explicit_filename_intent": filename_intent,
        }

        if cache_key and not degraded:
            global_query_cache.put(cache_key, res_dict)

        return res_dict

