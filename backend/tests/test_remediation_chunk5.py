"""Regression test suite for Remediation Chunk 5 (Findings 25-30).

Verifies:
- Finding 25: Unified Result Dict Helper in HybridRetriever
- Finding 26: TableData explicit __all__ export from app.intelligence.models
- Finding 27: Composite indexing_jobs claim and file_status indexes in schema migrations
- Finding 28: Bounded lexical overfetch limits [50, 200]
- Finding 29: Reranker context windowing (MAX_RERANKER_DOC_CHARS = 2000)
- Finding 30: Mutation-invalidated search query LRU cache
"""

import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.retrieval.hybrid import HybridRetriever, QueryCache, global_query_cache, invalidate_query_cache
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.normalizer import normalize_query
from app.retrieval.reranker import Reranker, MAX_RERANKER_DOC_CHARS, _sigmoid


# ============================================================================
# Finding 25: Unified Result Dict Helper
# ============================================================================
def test_finding_25_unified_result_dict():
    """Verify HybridRetriever._build_result_dict constructs consistent dictionary across all modes."""
    raw_item = {
        "chunk_id": "c1",
        "file_id": "f1",
        "score": 0.85,
        "source_file": "report.pdf",
        "source_path": "/data/report.pdf",
        "page": 3,
        "section": "Methods",
        "h1_parent": "Header 1",
        "h2_parent": "Header 2",
        "line_start": 10,
        "line_end": 25,
        "char_start": 100,
        "char_end": 500,
        "content": "This is sample content for testing the unified result dictionary helper.",
        "content_hash": "hash123",
        "metadata": {
            "sheet_name": "Sheet1",
            "slide_number": 5,
            "time_start": 12.5,
            "time_end": 18.0,
            "frame_index": 42,
            "media_type": "presentation",
            "extraction_method": "native_pptx",
        },
    }

    res = HybridRetriever._build_result_dict(
        item=raw_item,
        rank=1,
        query_tokens=["sample", "content"],
        retrieval_method="hybrid",
        score=0.92,
        rrf_score=0.032,
        lexical_score=12.5,
        dense_score=0.88,
        lexical_rank=1,
        dense_rank=2,
    )

    assert res["rank"] == 1
    assert res["chunk_id"] == "c1"
    assert res["file_id"] == "f1"
    assert res["score"] == 0.92
    assert res["rrf_score"] == 0.032
    assert res["lexical_score"] == 12.5
    assert res["dense_score"] == 0.88
    assert res["lexical_rank"] == 1
    assert res["dense_rank"] == 2
    assert res["retrieval_method"] == "hybrid"
    assert res["source_file"] == "report.pdf"
    assert res["page"] == 3
    assert res["sheet_name"] == "Sheet1"
    assert res["slide_number"] == 5
    assert res["time_start"] == 12.5
    assert res["time_end"] == 18.0
    assert res["frame_index"] == 42
    assert res["media_type"] == "presentation"
    assert res["extraction_method"] == "native_pptx"
    assert "sample content" in res["snippet"]


# ============================================================================
# Finding 26: TableData Export Hygiene
# ============================================================================
def test_finding_26_tabledata_export():
    """Verify TableData is explicitly exported from app.intelligence.models."""
    import app.intelligence.models as models_module

    assert hasattr(models_module, "TableData")
    assert "TableData" in models_module.__all__

    from app.intelligence.models import TableData
    t = TableData(headers=["A", "B"], rows=[["1", "2"]], caption="Test")
    assert t.caption == "Test"
    assert len(t.rows) == 1


# ============================================================================
# Finding 27: indexing_jobs Claim Index
# ============================================================================
def test_finding_27_job_claim_indexes(tmp_path):
    """Verify composite indexes idx_jobs_claim and idx_jobs_file_status exist in migrations."""
    db_path = tmp_path / "test_indexes.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)

    cur = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='indexing_jobs';"
    )
    indexes = {row["name"]: row["sql"] or "" for row in cur.fetchall()}

    assert "idx_jobs_claim" in indexes
    assert "idx_jobs_file_status" in indexes

    # Verify claim index covers status, priority, and created_at
    claim_sql = indexes["idx_jobs_claim"].upper()
    assert "STATUS" in claim_sql
    assert "PRIORITY" in claim_sql
    assert "CREATED_AT" in claim_sql
    conn.close()


# ============================================================================
# Finding 28: Bounded Lexical Overfetch
# ============================================================================
def test_finding_28_bounded_lexical_overfetch():
    """Verify LexicalRetriever bounds overfetch candidate pool between 50 and 200."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []

    retriever = LexicalRetriever(mock_conn)

    # For small top_k=5: min(max(5*3, 50), 200) -> 50
    q = normalize_query("quarterly financial report")
    retriever.search(q, top_k=5)
    called_sql, called_params = mock_conn.execute.call_args[0]
    assert called_params[-1] == 50  # LIMIT parameter

    # For medium top_k=30: min(max(30*3, 50), 200) -> 90
    retriever.search(q, top_k=30)
    called_sql, called_params = mock_conn.execute.call_args[0]
    assert called_params[-1] == 90  # LIMIT parameter

    # For large top_k=100: min(max(100*3, 50), 200) -> 200 (capped at 200, not 300)
    retriever.search(q, top_k=100)
    called_sql, called_params = mock_conn.execute.call_args[0]
    assert called_params[-1] == 200  # LIMIT parameter


# ============================================================================
# Finding 29: Reranker Context Windowing
# ============================================================================
def test_finding_29_reranker_context_windowing():
    """Verify Reranker truncates long document text to MAX_RERANKER_DOC_CHARS = 2000."""
    assert MAX_RERANKER_DOC_CHARS == 2000

    reranker = Reranker()
    mock_model = MagicMock()
    # FastEmbed TextCrossEncoder rerank returns an iterable of float scores
    mock_model.rerank.return_value = [2.0]
    reranker._model = mock_model
    reranker._loaded = True

    long_text = "Important data point. " + ("A" * 8000)
    candidates = [
        {
            "chunk_id": "c_long",
            "content": long_text,
            "score": 0.5,
            "rank": 1,
        }
    ]

    reranked = reranker.rerank(query="data point", candidates=candidates, top_k=1)
    assert len(reranked) == 1
    expected_score = round(_sigmoid(2.0), 6)
    assert reranked[0]["reranker_score"] == expected_score

    # Verify document passed to cross-encoder was truncated to <= 2000 chars
    mock_model.rerank.assert_called_once()
    called_args = mock_model.rerank.call_args[0]
    q_str = called_args[0]
    docs = called_args[1]
    assert q_str == "data point"
    assert len(docs[0]) == 2000
    assert docs[0].startswith("Important data point.")


# ============================================================================
# Finding 30: Mutation-Invalidated Query Cache
# ============================================================================
def test_finding_30_query_cache():
    """Verify QueryCache LRU behavior, HybridRetriever caching, and mutation invalidation."""
    cache = QueryCache(maxsize=3)
    assert cache.size == 0

    cache.put("q1", {"res": 1})
    cache.put("q2", {"res": 2})
    cache.put("q3", {"res": 3})
    assert cache.size == 3

    assert cache.get("q1") == {"res": 1}
    assert cache.get("nonexistent") is None

    # Adding a 4th key should evict oldest (q2 because q1 was accessed recently)
    cache.put("q4", {"res": 4})
    assert cache.size == 3
    assert cache.get("q2") is None
    assert cache.get("q1") == {"res": 1}
    assert cache.get("q4") == {"res": 4}

    # Invalidate
    cache.invalidate()
    assert cache.size == 0
    assert cache.get("q1") is None


def test_finding_30_hybrid_retriever_cache_integration(tmp_path):
    """Verify HybridRetriever utilizes global query cache and honors invalidation."""
    db_path = tmp_path / "test_hybrid_cache.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)

    # Insert a dummy file and chunk (triggers will populate chunks_fts automatically)
    conn.execute(
        """
        INSERT INTO files (file_id, folder_id, path, relative_path, filename, extension, size_bytes, modified_at, last_seen_at, index_status)
        VALUES ('f1', 'fld1', '/test/doc.txt', 'doc.txt', 'doc.txt', '.txt', 100, '2026-01-01T00:00:00', '2026-01-01T00:00:00', 'INDEXED');
        """
    )
    conn.execute(
        """
        INSERT INTO chunks (chunk_id, file_id, source_file, source_path, chunk_index, parser_name, parser_version, chunker_version, line_start, line_end, char_start, char_end, content, content_hash)
        VALUES ('c1', 'f1', 'doc.txt', '/test/doc.txt', 0, 'text_parser', '1.0', '1.0', 1, 10, 0, 100, 'Revenue growth was 25 percent in Q3.', 'hash1');
        """
    )
    conn.commit()

    retriever = HybridRetriever(
        db_conn=conn,
        embedding_engine=MagicMock(embed_query=MagicMock(return_value=[0.1] * 384)),
        vector_store=MagicMock(search=MagicMock(return_value=[])),
        reranker=None,
    )

    # Ensure clean cache state
    invalidate_query_cache()

    # Search 1: Cache Miss
    res1 = retriever.search("Revenue growth", top_k=5, mode="bm25")
    assert res1["total_found"] == 1
    assert global_query_cache.size >= 1

    # Search 2: Cache Hit
    res2 = retriever.search("Revenue growth", top_k=5, mode="bm25")
    assert res2["total_found"] == 1
    assert res2["results"][0]["chunk_id"] == "c1"

    # Invalidate cache
    invalidate_query_cache()
    assert global_query_cache.size == 0

    conn.close()
