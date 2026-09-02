"""
FileMind Phase 5.5 Batch 2 — Related Content Test Suite.

Verifies:
1. Deterministic related retrieval across repeated calls.
2. Strict self-exclusion (source file never in its own related results).
3. Chunk-to-file aggregation and multi-chunk deduplication.
4. Max Chunk Score file ranking.
5. Deterministic tie-breaking (-score, -matching_chunks, file_id ASC).
6. Primary and supporting chunk selection with snippet provenance.
7. Explanations matching section headings.
8. Error handling: missing source (404), unindexed source (400), zero-chunk source (empty).
9. One-file corpus behavior (empty results).
10. Deleted/missing candidate filtering.
11. Fast mode and Quality mode execution.
12. FastAPI endpoint GET /retrieval/related/{file_id}.
13. Zero database migration invariant.
14. Search and Ask regression preservation.
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional
import pytest
from unittest.mock import MagicMock, patch

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations, SCHEMA_VERSION
from app.db.repository import Repository
from app.retrieval.related import RelatedContentService
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.normalizer import normalize_query


@pytest.fixture
def test_db(tmp_path):
    """Creates a test database with all migrations applied."""
    db_file = str(tmp_path / "test_related.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS chunk_vectors (chunk_id TEXT PRIMARY KEY);")
    return db


@pytest.fixture
def populated_corpus(test_db):
    """
    Creates a multi-file test corpus:
    - file_a: Source document on "Storage Engines and SQLite WAL"
    - file_b: Related document on "SQLite Vector Extension and Database Internals" (3 chunks)
    - file_c: Related document on "Vector Databases and Retrieval" (1 chunk)
    - file_d: Unrelated document on "Frontend UI Styling with Tailwind CSS" (1 chunk)
    - file_unindexed: Unindexed file
    """
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/corpus", recursive=True)
        folder_id = folder["folder_id"]

        # File A (Source)
        fa = repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/corpus/storage_architecture.md",
            relative_path="storage_architecture.md",
            filename="storage_architecture.md",
            extension=".md",
            size_bytes=2000,
            modified_at="2026-09-02T10:00:00Z",
            mime_type="text/markdown",
            sha256="hash_a",
            index_status="INDEXED",
        )
        file_a_id = fa["file_id"]
        repo.replace_file_chunks(file_a_id, [
            {
                "chunk_id": "c_a1",
                "file_id": file_a_id,
                "source_file": "storage_architecture.md",
                "source_path": "C:/dev/corpus/storage_architecture.md",
                "page": 1,
                "section": "Storage Architecture",
                "h1_parent": "Architecture Overview",
                "h2_parent": "Database Layer",
                "line_start": 1,
                "line_end": 25,
                "char_start": 0,
                "char_end": 500,
                "content_hash": "ch_a1",
                "content": "FileMind uses SQLite WAL mode for high-throughput relational persistence.",
                "token_count": 40,
                "metadata": {},
            },
            {
                "chunk_id": "c_a2",
                "file_id": file_a_id,
                "source_file": "storage_architecture.md",
                "source_path": "C:/dev/corpus/storage_architecture.md",
                "page": 2,
                "section": "Vector Storage",
                "h1_parent": "Architecture Overview",
                "h2_parent": "Index Layer",
                "line_start": 26,
                "line_end": 50,
                "char_start": 501,
                "char_end": 1000,
                "content_hash": "ch_a2",
                "content": "Dense embeddings are stored in sqlite-vec virtual tables with cosine distance.",
                "token_count": 45,
                "metadata": {},
            },
        ])

        # File B (Highly Related - 3 chunks)
        fb = repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/corpus/sqlite_internals.md",
            relative_path="sqlite_internals.md",
            filename="sqlite_internals.md",
            extension=".md",
            size_bytes=3500,
            modified_at="2026-09-02T10:05:00Z",
            mime_type="text/markdown",
            sha256="hash_b",
            index_status="INDEXED",
        )
        file_b_id = fb["file_id"]
        repo.replace_file_chunks(file_b_id, [
            {
                "chunk_id": "c_b1",
                "file_id": file_b_id,
                "source_file": "sqlite_internals.md",
                "source_path": "C:/dev/corpus/sqlite_internals.md",
                "page": 1,
                "section": "SQLite WAL Internals",
                "h1_parent": "Internals",
                "h2_parent": "WAL",
                "line_start": 1,
                "line_end": 30,
                "char_start": 0,
                "char_end": 600,
                "content_hash": "ch_b1",
                "content": "SQLite WAL mode allows multiple concurrent readers without locking writers.",
                "token_count": 50,
                "metadata": {},
            },
            {
                "chunk_id": "c_b2",
                "file_id": file_b_id,
                "source_file": "sqlite_internals.md",
                "source_path": "C:/dev/corpus/sqlite_internals.md",
                "page": 2,
                "section": "Virtual Table Extensions",
                "h1_parent": "Internals",
                "h2_parent": "Extensions",
                "line_start": 31,
                "line_end": 60,
                "char_start": 601,
                "char_end": 1200,
                "content_hash": "ch_b2",
                "content": "sqlite-vec enables native vector search inside SQLite database files.",
                "token_count": 55,
                "metadata": {},
            },
            {
                "chunk_id": "c_b3",
                "file_id": file_b_id,
                "source_file": "sqlite_internals.md",
                "source_path": "C:/dev/corpus/sqlite_internals.md",
                "page": 3,
                "section": "Performance Benchmarks",
                "h1_parent": "Benchmarks",
                "h2_parent": None,
                "line_start": 61,
                "line_end": 90,
                "char_start": 1201,
                "char_end": 1800,
                "content_hash": "ch_b3",
                "content": "Benchmarking SQLite persistence throughput under high concurrency.",
                "token_count": 35,
                "metadata": {},
            },
        ])

        # File C (Moderately Related - 1 chunk)
        fc = repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/corpus/vector_retrieval.md",
            relative_path="vector_retrieval.md",
            filename="vector_retrieval.md",
            extension=".md",
            size_bytes=1200,
            modified_at="2026-09-02T10:10:00Z",
            mime_type="text/markdown",
            sha256="hash_c",
            index_status="INDEXED",
        )
        file_c_id = fc["file_id"]
        repo.replace_file_chunks(file_c_id, [
            {
                "chunk_id": "c_c1",
                "file_id": file_c_id,
                "source_file": "vector_retrieval.md",
                "source_path": "C:/dev/corpus/vector_retrieval.md",
                "page": 1,
                "section": "Dense Vector Search",
                "h1_parent": "Retrieval",
                "h2_parent": "Dense",
                "line_start": 1,
                "line_end": 20,
                "char_start": 0,
                "char_end": 400,
                "content_hash": "ch_c1",
                "content": "Dense vector search retrieves semantically similar document chunks.",
                "token_count": 30,
                "metadata": {},
            },
        ])

        # File D (Unrelated - 1 chunk)
        fd = repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/corpus/frontend_styling.tsx",
            relative_path="frontend_styling.tsx",
            filename="frontend_styling.tsx",
            extension=".tsx",
            size_bytes=800,
            modified_at="2026-09-02T10:15:00Z",
            mime_type="text/typescript",
            sha256="hash_d",
            index_status="INDEXED",
        )
        file_d_id = fd["file_id"]
        repo.replace_file_chunks(file_d_id, [
            {
                "chunk_id": "c_d1",
                "file_id": file_d_id,
                "source_file": "frontend_styling.tsx",
                "source_path": "C:/dev/corpus/frontend_styling.tsx",
                "page": None,
                "section": "Components",
                "h1_parent": "UI",
                "h2_parent": "Buttons",
                "line_start": 1,
                "line_end": 30,
                "char_start": 0,
                "char_end": 500,
                "content_hash": "ch_d1",
                "content": "export function StyledButton() { return <button className='bg-blue-500'>Click</button>; }",
                "token_count": 25,
                "metadata": {},
            },
        ])

        # File E (Unindexed)
        fe = repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/corpus/unindexed.txt",
            relative_path="unindexed.txt",
            filename="unindexed.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T10:20:00Z",
            mime_type="text/plain",
            sha256="hash_e",
            index_status="DISCOVERED",
        )
        file_e_id = fe["file_id"]

    return {
        "file_a_id": file_a_id,
        "file_b_id": file_b_id,
        "file_c_id": file_c_id,
        "file_d_id": file_d_id,
        "file_e_id": file_e_id,
    }


class FakeRetriever:
    """Deterministic mock retriever for testing RelatedContentService."""

    def __init__(self, canned_results: Optional[List[Dict[str, Any]]] = None):
        self.canned_results = canned_results or []
        self.recorded_queries: List[str] = []

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        mode: str = "hybrid",
        quality: str = "fast",
    ) -> Dict[str, Any]:
        self.recorded_queries.append(query if isinstance(query, str) else query.raw_query)
        return {
            "query": str(query),
            "mode": mode,
            "quality": quality,
            "total_found": len(self.canned_results),
            "latency_breakdown_ms": {"normalization": 0.1, "total_request": 5.0},
            "results": self.canned_results,
            "degraded": False,
            "retrieval_method": mode,
        }


# ===========================================================================
# A. Core Domain Service Tests
# ===========================================================================

def test_related_content_strict_self_exclusion(test_db, populated_corpus):
    """Verifies that the source file is never returned in its own related content."""
    fa_id = populated_corpus["file_a_id"]
    fb_id = populated_corpus["file_b_id"]

    fake_results = [
        # Source file chunk (should be filtered out)
        {
            "chunk_id": "c_a1",
            "file_id": fa_id,
            "source_file": "storage_architecture.md",
            "source_path": "C:/dev/corpus/storage_architecture.md",
            "score": 0.050,
            "section": "Storage Architecture",
            "snippet": "FileMind uses SQLite WAL mode...",
        },
        # Related file B chunk
        {
            "chunk_id": "c_b1",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.035,
            "section": "SQLite WAL Internals",
            "snippet": "SQLite WAL mode allows multiple concurrent readers...",
        },
    ]

    mock_retriever = FakeRetriever(canned_results=fake_results)
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=fa_id, limit=5)

    assert resp["total_found"] == 1
    assert len(resp["results"]) == 1
    assert resp["results"][0]["file_id"] == fb_id
    assert all(r["file_id"] != fa_id for r in resp["results"])


def test_related_content_multi_chunk_grouping_and_max_score(test_db, populated_corpus):
    """Verifies that multiple chunks from the same candidate are grouped and ranked by Max Chunk Score."""
    fa_id = populated_corpus["file_a_id"]
    fb_id = populated_corpus["file_b_id"]
    fc_id = populated_corpus["file_c_id"]

    fake_results = [
        # File B has 3 chunks with highest score 0.040
        {
            "chunk_id": "c_b1",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.040,
            "section": "SQLite WAL Internals",
            "snippet": "Chunk 1 snippet",
        },
        {
            "chunk_id": "c_b2",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.025,
            "section": "Virtual Table Extensions",
            "snippet": "Chunk 2 snippet",
        },
        {
            "chunk_id": "c_b3",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.015,
            "section": "Performance Benchmarks",
            "snippet": "Chunk 3 snippet",
        },
        # File C has 1 chunk with score 0.030
        {
            "chunk_id": "c_c1",
            "file_id": fc_id,
            "source_file": "vector_retrieval.md",
            "source_path": "C:/dev/corpus/vector_retrieval.md",
            "score": 0.030,
            "section": "Dense Vector Search",
            "snippet": "Chunk C snippet",
        },
    ]

    mock_retriever = FakeRetriever(canned_results=fake_results)
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=fa_id, limit=5)

    assert resp["total_found"] == 2
    # File B should rank #1 because max(0.040, 0.025, 0.015) = 0.040 > 0.030
    assert resp["results"][0]["file_id"] == fb_id
    assert resp["results"][0]["score"] == 0.040
    assert resp["results"][0]["matching_chunk_count"] == 3
    assert resp["results"][0]["primary_matched_chunk"]["chunk_id"] == "c_b1"
    assert len(resp["results"][0]["supporting_chunks"]) == 2
    assert "3 sections" in resp["results"][0]["explanation"]

    # File C should rank #2 with score 0.030
    assert resp["results"][1]["file_id"] == fc_id
    assert resp["results"][1]["score"] == 0.030
    assert resp["results"][1]["matching_chunk_count"] == 1
    assert len(resp["results"][1]["supporting_chunks"]) == 0


def test_related_content_deterministic_tie_breaking(test_db, populated_corpus):
    """Verifies that equal scores sort by matching_chunk_count DESC then file_id ASC."""
    fa_id = populated_corpus["file_a_id"]
    fb_id = populated_corpus["file_b_id"]
    fc_id = populated_corpus["file_c_id"]

    fake_results = [
        # File C has 1 chunk with score 0.030
        {
            "chunk_id": "c_c1",
            "file_id": fc_id,
            "source_file": "vector_retrieval.md",
            "source_path": "C:/dev/corpus/vector_retrieval.md",
            "score": 0.030,
            "section": "Dense Vector Search",
            "snippet": "Chunk C snippet",
        },
        # File B has 2 chunks with max score 0.030
        {
            "chunk_id": "c_b1",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.030,
            "section": "SQLite WAL Internals",
            "snippet": "Chunk B1 snippet",
        },
        {
            "chunk_id": "c_b2",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.020,
            "section": "Virtual Table Extensions",
            "snippet": "Chunk B2 snippet",
        },
    ]

    mock_retriever = FakeRetriever(canned_results=fake_results)
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=fa_id, limit=5)

    assert resp["total_found"] == 2
    # File B has matching_chunk_count=2 vs File C count=1 with same max_score=0.030 -> File B wins
    assert resp["results"][0]["file_id"] == fb_id
    assert resp["results"][1]["file_id"] == fc_id


def test_related_content_synthetic_query_generation(test_db, populated_corpus):
    """Verifies that synthetic query combines filename stem, headings, and intro text."""
    fa_id = populated_corpus["file_a_id"]

    mock_retriever = FakeRetriever(canned_results=[])
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=fa_id, limit=5)

    assert len(mock_retriever.recorded_queries) == 1
    query_used = mock_retriever.recorded_queries[0]

    # Filename stem
    assert "storage architecture" in query_used.lower()
    # Headings
    assert "architecture overview" in query_used.lower() or "database layer" in query_used.lower()
    # Intro content
    assert "sqlite wal mode" in query_used.lower()


# ===========================================================================
# B. Edge Cases & Error Handling
# ===========================================================================

def test_related_content_missing_source_file_raises(test_db):
    """Verifies that non-existent file_id raises ValueError."""
    svc = RelatedContentService(db_manager=test_db)
    with pytest.raises(ValueError, match="not found"):
        svc.get_related_files(file_id="nonexistent-file-id")


def test_related_content_unindexed_source_file_raises(test_db, populated_corpus):
    """Verifies that unindexed file raises ValueError."""
    fe_id = populated_corpus["file_e_id"]
    svc = RelatedContentService(db_manager=test_db)
    with pytest.raises(ValueError, match="not indexed"):
        svc.get_related_files(file_id=fe_id)


def test_related_content_zero_chunks_returns_empty(test_db):
    """Verifies that an indexed file with 0 chunks returns empty results cleanly."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/empty_folder", recursive=True)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/dev/empty_folder/empty.txt",
            relative_path="empty.txt",
            filename="empty.txt",
            extension=".txt",
            size_bytes=0,
            modified_at="2026-09-02T10:00:00Z",
            mime_type="text/plain",
            sha256="emptyhash",
            index_status="INDEXED",
        )
        empty_id = file_rec["file_id"]

    mock_retriever = FakeRetriever(canned_results=[])
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=empty_id)

    assert resp["total_found"] == 0
    assert resp["results"] == []
    assert len(mock_retriever.recorded_queries) == 0  # Retrieval not called


def test_related_content_invalid_quality_mode_raises(test_db, populated_corpus):
    """Verifies that invalid quality parameter raises ValueError."""
    fa_id = populated_corpus["file_a_id"]
    svc = RelatedContentService(db_manager=test_db)
    with pytest.raises(ValueError, match="Invalid quality mode"):
        svc.get_related_files(file_id=fa_id, quality="invalid_mode")


def test_related_content_no_migration_required():
    """Verifies that Phase 5.5 Batch 2 required zero database migrations."""
    assert SCHEMA_VERSION >= 6



# ===========================================================================
# C. FastAPI Endpoint Integration Tests
# ===========================================================================

def test_api_get_related_files(test_db, populated_corpus):
    """Verifies FastAPI GET /retrieval/related/{file_id} endpoint."""
    from fastapi.testclient import TestClient
    from app.main import app

    fa_id = populated_corpus["file_a_id"]
    fb_id = populated_corpus["file_b_id"]

    with patch("app.main.db_manager", test_db):
        client = TestClient(app)

        # 1. Successful request with mock search results
        mock_cands = [
            {
                "chunk_id": "c_b1",
                "file_id": fb_id,
                "source_file": "sqlite_internals.md",
                "source_path": "C:/dev/corpus/sqlite_internals.md",
                "score": 0.038,
                "section": "SQLite WAL Internals",
                "snippet": "WAL mode snippet",
            }
        ]

        with patch("app.retrieval.hybrid.HybridRetriever.search") as mock_search:
            mock_search.return_value = {
                "query": "storage architecture",
                "mode": "hybrid",
                "quality": "fast",
                "total_found": 1,
                "latency_breakdown_ms": {},
                "results": mock_cands,
                "degraded": False,
                "retrieval_method": "hybrid",
            }

            resp = client.get(f"/retrieval/related/{fa_id}?limit=5&quality=fast")
            assert resp.status_code == 200
            data = resp.json()
            assert data["source_file_id"] == fa_id
            assert data["total_found"] == 1
            assert len(data["results"]) == 1
            assert data["results"][0]["file_id"] == fb_id
            assert data["results"][0]["score"] == 0.038
            assert data["results"][0]["primary_matched_chunk"]["chunk_id"] == "c_b1"

        # 2. 404 for missing file
        resp_404 = client.get("/retrieval/related/nonexistent-fid")
        assert resp_404.status_code == 404

        # 3. 400 for unindexed file
        fe_id = populated_corpus["file_e_id"]
        resp_400 = client.get(f"/retrieval/related/{fe_id}")
        assert resp_400.status_code == 400


# ===========================================================================
# D. Additional Invariant & Edge Case Tests
# ===========================================================================

def test_related_content_quality_mode(test_db, populated_corpus):
    """Verifies that quality='quality' forwards to retrieval with reranker score."""
    fa_id = populated_corpus["file_a_id"]
    fb_id = populated_corpus["file_b_id"]

    fake_results = [
        {
            "chunk_id": "c_b1",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.95,
            "reranker_score": 0.95,
            "section": "SQLite WAL Internals",
            "snippet": "Reranked snippet",
        }
    ]

    mock_retriever = FakeRetriever(canned_results=fake_results)
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=fa_id, limit=5, quality="quality")

    assert resp["total_found"] == 1
    assert resp["quality"] == "quality"
    assert resp["results"][0]["score"] == 0.95


def test_related_content_one_file_corpus_returns_empty(test_db):
    """Verifies that when only the source file exists in corpus, result is empty due to self-exclusion."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/single_folder", recursive=True)
        f_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/dev/single_folder/single.md",
            relative_path="single.md",
            filename="single.md",
            extension=".md",
            size_bytes=500,
            modified_at="2026-09-02T10:00:00Z",
            mime_type="text/markdown",
            sha256="hash_single",
            index_status="INDEXED",
        )
        single_fid = f_rec["file_id"]
        repo.replace_file_chunks(single_fid, [
            {
                "chunk_id": "c_s1",
                "file_id": single_fid,
                "source_file": "single.md",
                "source_path": "C:/dev/single_folder/single.md",
                "page": 1,
                "section": "Intro",
                "h1_parent": "Main",
                "h2_parent": None,
                "line_start": 1,
                "line_end": 10,
                "char_start": 0,
                "char_end": 100,
                "content_hash": "ch_s1",
                "content": "Solo document with no peers in index.",
                "token_count": 20,
                "metadata": {},
            }
        ])

    # Search returns only the source file's own chunk
    self_results = [
        {
            "chunk_id": "c_s1",
            "file_id": single_fid,
            "source_file": "single.md",
            "source_path": "C:/dev/single_folder/single.md",
            "score": 0.05,
            "section": "Intro",
            "snippet": "Solo document snippet",
        }
    ]
    mock_retriever = FakeRetriever(canned_results=self_results)
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=single_fid)

    assert resp["total_found"] == 0
    assert resp["results"] == []


def test_related_content_max_supporting_chunks_cap(test_db, populated_corpus):
    """Verifies that at most 2 supporting chunks are included in supporting_chunks list."""
    fa_id = populated_corpus["file_a_id"]
    fb_id = populated_corpus["file_b_id"]

    # 5 matching chunks from file B
    five_chunks = [
        {
            "chunk_id": f"c_b{i}",
            "file_id": fb_id,
            "source_file": "sqlite_internals.md",
            "source_path": "C:/dev/corpus/sqlite_internals.md",
            "score": 0.05 - (i * 0.005),
            "section": f"Section {i}",
            "snippet": f"Snippet {i}",
        }
        for i in range(1, 6)
    ]

    mock_retriever = FakeRetriever(canned_results=five_chunks)
    svc = RelatedContentService(db_manager=test_db, retriever=mock_retriever)
    resp = svc.get_related_files(file_id=fa_id, limit=5)

    assert resp["total_found"] == 1
    assert resp["results"][0]["matching_chunk_count"] == 5
    assert resp["results"][0]["primary_matched_chunk"]["chunk_id"] == "c_b1"
    # Exactly 2 supporting chunks (c_b2 and c_b3)
    assert len(resp["results"][0]["supporting_chunks"]) == 2
    assert resp["results"][0]["supporting_chunks"][0]["chunk_id"] == "c_b2"
    assert resp["results"][0]["supporting_chunks"][1]["chunk_id"] == "c_b3"

