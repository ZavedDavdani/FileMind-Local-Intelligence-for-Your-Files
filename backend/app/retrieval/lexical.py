"""Deterministic SQLite FTS5 / BM25 lexical retrieval engine for Phase 3."""

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Union

from app.retrieval.normalizer import NormalizedQuery, normalize_query

logger = logging.getLogger("FileMind.Retrieval.Lexical")

# Field weights for FTS5 bm25(): content, h1_parent, h2_parent, section, source_file
BM25_WEIGHT_CONTENT = 5.0
BM25_WEIGHT_H1 = 2.0
BM25_WEIGHT_H2 = 1.5
BM25_WEIGHT_SECTION = 1.0
BM25_WEIGHT_FILE = 2.0


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

        # Never return chunks from deleted/missing files
        where_clauses.append("f.index_status != 'MISSING'")

        where_sql = " AND ".join(where_clauses)
        params.append(top_k)

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
        JOIN chunks c ON c.rowid = chunks_fts.rowid
        JOIN files f ON f.file_id = c.file_id
        WHERE {where_sql}
        ORDER BY raw_bm25_score ASC, c.chunk_id ASC
        LIMIT ?;
        """

        try:
            cursor = self.conn.execute(sql, params)
            rows = cursor.fetchall()
        except sqlite3.OperationalError as err:
            logger.warning("FTS5 query execution warning: %s for query: %s", str(err), norm_q.fts5_query)
            return []

        results = []
        for rank, row in enumerate(rows, start=1):
            d = dict(row) if isinstance(row, sqlite3.Row) else {
                col[0]: row[i] for i, col in enumerate(cursor.description)
            }
            # Convert raw BM25 score (negative) to a positive normalized relevance score
            raw_score = d["raw_bm25_score"]
            # BM25 is unbounded negative where more negative is better match
            positive_score = round(abs(raw_score), 4)

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

        return results
