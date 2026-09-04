"""Deterministic SQLite FTS5 / BM25 lexical retrieval engine for Phase 3."""

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from app.retrieval.normalizer import NormalizedQuery, normalize_query

logger = logging.getLogger("FileMind.Retrieval.Lexical")

# Field weights for FTS5 bm25(): content, h1_parent, h2_parent, section, source_file
BM25_WEIGHT_CONTENT = 5.0
BM25_WEIGHT_H1 = 2.0
BM25_WEIGHT_H2 = 1.5
BM25_WEIGHT_SECTION = 1.0
BM25_WEIGHT_FILE = 15.0


def extract_filename_stems(source_file: str) -> Tuple[str, str]:
    """
    Extracts canonical direct stem and root stem from a filename.

    Examples:
    - 'archive.tar.gz' -> direct: 'archive.tar', root: 'archive'
    - 'report.final.pdf' -> direct: 'report.final', root: 'report'
    - 'sample.txt' -> direct: 'sample', root: 'sample'
    - 'README' -> direct: 'README', root: 'README'
    - 'archive.tar' -> direct: 'archive', root: 'archive'
    """
    if not source_file:
        return ("", "")
    sf = source_file.strip()
    direct_stem = sf.rsplit(".", 1)[0] if "." in sf else sf
    root_stem = sf.split(".", 1)[0] if "." in sf else sf
    return (direct_stem, root_stem)


def compute_filename_match_boost(
    query_lower: str,
    tokens: List[str],
    source_file: str,
    domain: str,
) -> float:
    """Computes a filename/stem relevance boost calibrated for the given scoring domain.

    Scoring domains:
    - ``"bm25"``: Adds to the positive BM25 score (abs of FTS5 raw score).
      Boosts are on the order of 2–5 points, consistent with typical BM25 score magnitudes.
    - ``"rrf"``: Adds to the RRF score (range ~0..0.033 per arm).
      Boosts are calibrated to the RRF ceiling (~0.033 at rank 1 with k=60).

    Both domains share the same match-category semantics:
      1. Exact filename or exact stem match (highest priority)
      2. Any query token exactly equals the filename
      3. Any query token matches a stem

    Args:
        query_lower: The normalized raw query string in lowercase.
        tokens: The tokenized query terms.
        source_file: The source_file field from the chunk (lowercase expected from caller).
        domain: ``"bm25"`` or ``"rrf"``.

    Returns:
        Float boost to add to the candidate score. Returns 0.0 if no match.
    """
    sf = source_file.lower()
    direct_stem, root_stem = extract_filename_stems(sf)
    stems = {direct_stem.lower(), root_stem.lower()}

    if domain == "bm25":
        # BM25 additive boosts (in units of abs(bm25_score))
        if query_lower == sf or query_lower in stems:
            return 5.0
        if any(tok.lower() == sf for tok in tokens if len(tok) >= 2):
            return 3.0
        if any(tok.lower() in stems for tok in tokens if len(tok) >= 2):
            return 2.0
        return 0.0

    elif domain == "rrf":
        # RRF additive boosts (calibrated to RRF score range ~0..0.033/arm)
        # Exact filename/stem: conditional promotion for top-ranked lexical hits
        # to ensure file discovery without exceeding the RRF ceiling.
        if query_lower == sf or query_lower in stems:
            # Caller must apply the lex_rank conditioning if desired;
            # this helper returns the base "exact match" boost.
            return 0.0200
        if any(tok.lower() == sf for tok in tokens if len(tok) >= 2):
            return 0.0080
        if any(tok.lower() in stems for tok in tokens if len(tok) >= 2):
            return 0.0050
        return 0.0

    return 0.0


class LexicalRetriever:
    """Provides fast, deterministic BM25 lexical search over SQLite FTS5 index."""

    def __init__(self, db_conn: sqlite3.Connection):
        self.conn = db_conn

    def search(
        self,
        query: Union[str, NormalizedQuery],
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Executes BM25 search against chunks_fts table with optional metadata filters.
        
        Supported filters:
        - folder_id (str)
        - extension (str, e.g. ".pdf" or "pdf")
        - file_id (str)
        - source_path (str)
        """
        if isinstance(query, str):
            norm_q = normalize_query(query)
        else:
            norm_q = query

        if norm_q.is_empty or not norm_q.fts5_query:
            return []

        filters = filters or {}
        where_clauses = ["chunks_fts MATCH ?"]
        params: List[Any] = [norm_q.fts5_query]

        # Metadata filters
        if filters.get("folder_id"):
            where_clauses.append("f.folder_id = ?")
            params.append(filters["folder_id"])

        if filters.get("extension"):
            ext = filters["extension"].lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            where_clauses.append("LOWER(f.extension) = ?")
            params.append(ext)

        if filters.get("file_id"):
            where_clauses.append("c.file_id = ?")
            params.append(filters["file_id"])

        if filters.get("source_path"):
            where_clauses.append("c.source_path = ?")
            params.append(filters["source_path"])

        # Exclude non-indexed, failed, missing, and skipped files
        where_clauses.append("f.index_status NOT IN ('MISSING', 'FAILED', 'SKIPPED')")

        where_sql = " AND ".join(where_clauses)
        fetch_limit = max(top_k * 5, 200)
        params.append(fetch_limit)

        # FTS5 bm25 returns lower/negative values for better matches.
        # Order by bm25 score ASC, then chunk_id ASC for deterministic tie-breaking.
        sql = f"""
        SELECT 
            c.chunk_id,
            c.file_id,
            c.source_file,
            c.source_path,
            c.page,
            c.section,
            c.h1_parent,
            c.h2_parent,
            c.line_start,
            c.line_end,
            c.char_start,
            c.char_end,
            c.content_hash,
            c.chunk_index,
            c.content,
            c.metadata_json,
            bm25(chunks_fts, {BM25_WEIGHT_CONTENT}, {BM25_WEIGHT_H1}, {BM25_WEIGHT_H2}, {BM25_WEIGHT_SECTION}, {BM25_WEIGHT_FILE}) AS raw_bm25_score
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        JOIN files f ON f.file_id = c.file_id
        WHERE {where_sql}
        ORDER BY raw_bm25_score ASC, c.chunk_id ASC
        LIMIT ?;
        """

        cursor = self.conn.execute(sql, params)
        rows = cursor.fetchall()

        q_raw_lower = (norm_q.raw_query or "").lower().strip()

        results = []
        for rank, row in enumerate(rows, start=1):
            d = dict(row) if isinstance(row, sqlite3.Row) else {
                col[0]: row[i] for i, col in enumerate(cursor.description)
            }
            raw_score = d["raw_bm25_score"]
            positive_score = round(abs(raw_score), 4)

            # Filename relevance bonus for exact filename or stem matches
            sf = (d.get("source_file") or "").lower()
            positive_score += compute_filename_match_boost(q_raw_lower, norm_q.tokens, sf, domain="bm25")

            try:
                meta = json.loads(d.get("metadata_json") or "{}")
            except Exception:
                meta = {}

            results.append({
                "rank": rank,
                "chunk_id": d["chunk_id"],
                "file_id": d["file_id"],
                "score": positive_score,
                "raw_bm25_score": raw_score,
                "retrieval_method": "bm25",
                "source_file": d["source_file"],
                "source_path": d["source_path"],
                "page": d.get("page"),
                "section": d.get("section"),
                "h1_parent": d.get("h1_parent"),
                "h2_parent": d.get("h2_parent"),
                "line_start": d.get("line_start"),
                "line_end": d.get("line_end"),
                "char_start": d.get("char_start"),
                "char_end": d.get("char_end"),
                "content": d["content"],
                "content_hash": d["content_hash"],
                "metadata": meta,
            })

        # Re-sort by score DESC, then chunk_id ASC for deterministic ranking
        results.sort(key=lambda x: (-x["score"], x["chunk_id"]))
        results = results[:top_k]
        for rank, res in enumerate(results, start=1):
            res["rank"] = rank

        return results
