"""Comprehensive regression tests for Batch 3:
- Bug #2: Hybrid latency breakdown timing independence
- Bug #4: MemoryCosineStore filter support and error handling
- Bug #5: LanceDBVectorStore contract parity, safe deletes, accurate counts, and upsert
"""

import os
import shutil
import tempfile
import time
import sqlite3
import numpy as np
import pytest
from typing import Any, Dict, List, Optional

from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_store import (
    BaseVectorStore,
    LanceDBVectorStore,
    MemoryCosineStore,
)
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.normalizer import normalize_query


# ---------------------------------------------------------------------------
# Bug #2: Hybrid Latency Timing Independence
# ---------------------------------------------------------------------------

class SimulatedTimedEmbeddingEngine:
    def __init__(self, embed_delay_s: float = 0.05):
        self.dimension = 4
        self.embed_delay_s = embed_delay_s

    def embed_query(self, query: str) -> List[float]:
        time.sleep(self.embed_delay_s)
        return [1.0, 0.0, 0.0, 0.0]

    def embed_chunks(self, chunks: List[Dict[str, Any]]) -> List[List[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in chunks]


class SimulatedTimedVectorStore(BaseVectorStore):
    def __init__(self, search_delay_s: float = 0.03):
        self.search_delay_s = search_delay_s

    def initialize(self):
        pass

    def upsert_vectors(self, records: List[Dict[str, Any]]) -> int:
        return len(records)

    def search(
        self,
        query_vector: List[float],
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        time.sleep(self.search_delay_s)
        return [
            {
                "chunk_id": "c1",
                "file_id": "f1",
                "score": 0.95,
                "source_file": "test.txt",
                "source_path": "/test.txt",
                "content": "Test content",
                "content_hash": "h1",
            }
        ]

    def delete_by_chunk_ids(self, chunk_ids: List[str]) -> int:
        return len(chunk_ids)

    def delete_by_file_id(self, file_id: str) -> int:
        return 1

    def count(self) -> int:
        return 1


class MockLexicalRetriever:
    def __init__(self, search_delay_s: float = 0.02):
        self.search_delay_s = search_delay_s

    def search(self, norm_q, top_k=50, filters=None):
        time.sleep(self.search_delay_s)
        return [
            {
                "chunk_id": "c1",
                "file_id": "f1",
                "score": 10.0,
                "source_file": "test.txt",
                "source_path": "/test.txt",
                "content": "Test content",
                "content_hash": "h1",
            }
        ]


def test_bug2_hybrid_latency_breakdown_measures_independent_stages():
    """Bug #2: Verify that dense_search latency measures ONLY vector_store.search()
    and does not double-count query_embedding time."""
    conn = sqlite3.connect(":memory:")

    embed_delay = 0.040  # 40ms
    search_delay = 0.020  # 20ms
    lex_delay = 0.015  # 15ms

    embed_engine = SimulatedTimedEmbeddingEngine(embed_delay_s=embed_delay)
    vec_store = SimulatedTimedVectorStore(search_delay_s=search_delay)

    retriever = HybridRetriever(
        conn,
        embedding_engine=embed_engine,
        vector_store=vec_store,
    )
    retriever.lexical_retriever = MockLexicalRetriever(search_delay_s=lex_delay)

    resp = retriever.search("test query", top_k=5, mode="hybrid")
    latencies = resp["latency_breakdown_ms"]

    embed_ms = latencies["query_embedding"]
    dense_ms = latencies["dense_search"]
    lex_ms = latencies["lexical_search"]
    total_ms = latencies["total_request"]

    # query_embedding should be ~40ms (>= 35ms)
    assert embed_ms >= 35.0, f"Expected query_embedding >= 35ms, got {embed_ms}"
    # dense_search should be ~20ms (>= 15ms and < 35ms)
    assert dense_ms >= 15.0, f"Expected dense_search >= 15ms, got {dense_ms}"
    # Crucial: dense_search must NOT contain query_embedding (~60ms)
    assert dense_ms < embed_ms, (
        f"dense_search ({dense_ms}ms) double-counted query_embedding ({embed_ms}ms)!"
    )
    # Total request time must be at least the sum of independent stages
    assert total_ms >= (embed_ms + dense_ms + lex_ms - 5.0)


# ---------------------------------------------------------------------------
# Bug #4: MemoryCosineStore Filtering and Error Handling
# ---------------------------------------------------------------------------

def test_bug4_memory_cosine_store_file_id_filter():
    """Bug #4: MemoryCosineStore applies file_id filter correctly."""
    store = MemoryCosineStore(dimension=4)
    records = [
        {"chunk_id": "c1", "file_id": "f_alpha", "embedding": [1.0, 0.0, 0.0, 0.0]},
        {"chunk_id": "c2", "file_id": "f_alpha", "embedding": [0.8, 0.2, 0.0, 0.0]},
        {"chunk_id": "c3", "file_id": "f_beta", "embedding": [1.0, 0.0, 0.0, 0.0]},
        {"chunk_id": "c4", "file_id": "f_gamma", "embedding": [0.0, 1.0, 0.0, 0.0]},
    ]
    store.upsert_vectors(records)
    assert store.count() == 4

    # Search with file_id=f_alpha
    res = store.search([1.0, 0.0, 0.0, 0.0], top_k=10, filters={"file_id": "f_alpha"})
    assert len(res) == 2
    assert {r["chunk_id"] for r in res} == {"c1", "c2"}
    assert all(r["file_id"] == "f_alpha" for r in res)

    # Search with file_id=f_beta
    res_beta = store.search([1.0, 0.0, 0.0, 0.0], top_k=10, filters={"file_id": "f_beta"})
    assert len(res_beta) == 1
    assert res_beta[0]["chunk_id"] == "c3"

    # Search with non-existent file_id
    res_none = store.search([1.0, 0.0, 0.0, 0.0], top_k=10, filters={"file_id": "non_existent"})
    assert len(res_none) == 0


def test_bug4_memory_cosine_store_unsupported_filters_raise():
    """Bug #4: MemoryCosineStore explicitly rejects unsupported filters rather than silently ignoring them."""
    store = MemoryCosineStore(dimension=4)
    store.upsert_vectors([
        {"chunk_id": "c1", "file_id": "f1", "embedding": [1.0, 0.0, 0.0, 0.0]},
    ])

    with pytest.raises(ValueError) as excinfo:
        store.search([1.0, 0.0, 0.0, 0.0], top_k=5, filters={"folder_id": "fld_1"})
    assert "folder_id" in str(excinfo.value)
    assert "only supports 'file_id' filter" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo2:
        store.search([1.0, 0.0, 0.0, 0.0], top_k=5, filters={"extension": ".pdf", "file_id": "f1"})
    assert "extension" in str(excinfo2.value)


def test_bug4_memory_cosine_store_deletions_and_counts():
    """Bug #4: MemoryCosineStore accurately tracks deletions and row counts."""
    store = MemoryCosineStore(dimension=4)
    records = [
        {"chunk_id": "c1", "file_id": "f1", "embedding": [1.0, 0.0, 0.0, 0.0]},
        {"chunk_id": "c2", "file_id": "f1", "embedding": [0.0, 1.0, 0.0, 0.0]},
        {"chunk_id": "c3", "file_id": "f2", "embedding": [0.0, 0.0, 1.0, 0.0]},
    ]
    store.upsert_vectors(records)
    assert store.count() == 3

    # Delete by chunk_id
    del_c = store.delete_by_chunk_ids(["c1", "nonexistent"])
    assert del_c == 1
    assert store.count() == 2

    # Delete by file_id
    del_f = store.delete_by_file_id("f1")
    assert del_f == 1
    assert store.count() == 1

    # Remaining record is c3
    assert store.chunk_ids == ["c3"]
    assert store.file_ids == ["f2"]


# ---------------------------------------------------------------------------
# Bug #5: LanceDBVectorStore Contract, Upsert, Security, Accurate Counts
# ---------------------------------------------------------------------------

@pytest.fixture
def lancedb_store():
    temp_dir = tempfile.mkdtemp(prefix="filemind_test_lancedb_")
    db_path = os.path.join(temp_dir, "test_lancedb")
    store = LanceDBVectorStore(db_path=db_path, table_name="test_vectors", dimension=4)
    yield store
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_bug5_lancedb_upsert_prevents_duplicate_chunks(lancedb_store):
    """Bug #5: LanceDB upsert overwrites existing chunk_ids without creating duplicates."""
    records_initial = [
        {"chunk_id": "c1", "file_id": "f1", "embedding": [1.0, 0.0, 0.0, 0.0]},
        {"chunk_id": "c2", "file_id": "f1", "embedding": [0.0, 1.0, 0.0, 0.0]},
    ]
    n1 = lancedb_store.upsert_vectors(records_initial)
    assert n1 == 2
    assert lancedb_store.count() == 2

    # Re-upsert c1 with updated vector
    records_updated = [
        {"chunk_id": "c1", "file_id": "f1", "embedding": [0.5, 0.5, 0.0, 0.0]},
        {"chunk_id": "c3", "file_id": "f2", "embedding": [0.0, 0.0, 1.0, 0.0]},
    ]
    n2 = lancedb_store.upsert_vectors(records_updated)
    assert n2 == 2
    # Total count must be 3 (c1, c2, c3), NOT 4!
    assert lancedb_store.count() == 3

    # Searching should return updated vector distance for c1
    res = lancedb_store.search([0.5, 0.5, 0.0, 0.0], top_k=1)
    assert len(res) == 1
    assert res[0]["chunk_id"] == "c1"


def test_bug5_lancedb_safe_deletes_with_special_identifiers(lancedb_store):
    """Bug #5: Deletions handle normal-id, id-with-hyphen, and id'with'quote safely without injection."""
    records = [
        {"chunk_id": "normal-id", "file_id": "f-normal", "embedding": [1.0, 0.0, 0.0, 0.0]},
        {"chunk_id": "id-with-hyphen-123", "file_id": "f-hyphen", "embedding": [0.0, 1.0, 0.0, 0.0]},
        {"chunk_id": "id'with'quote'and'sql", "file_id": "f'quote'file", "embedding": [0.0, 0.0, 1.0, 0.0]},
        {"chunk_id": "safe_record", "file_id": "f_safe", "embedding": [0.0, 0.0, 0.0, 1.0]},
    ]
    lancedb_store.upsert_vectors(records)
    assert lancedb_store.count() == 4

    # 1. Delete id-with-hyphen
    deleted = lancedb_store.delete_by_chunk_ids(["id-with-hyphen-123"])
    assert deleted == 1
    assert lancedb_store.count() == 3

    # 2. Delete id'with'quote'and'sql (adversarial SQL injection payload)
    deleted_quote = lancedb_store.delete_by_chunk_ids(["id'with'quote'and'sql"])
    assert deleted_quote == 1
    assert lancedb_store.count() == 2

    # 3. Delete by file_id with quote
    deleted_f_quote = lancedb_store.delete_by_file_id("f'quote'file")
    # Record was already deleted by chunk_id, so count should be 0
    assert deleted_f_quote == 0
    assert lancedb_store.count() == 2

    # 4. Delete f-normal
    deleted_f = lancedb_store.delete_by_file_id("f-normal")
    assert deleted_f == 1
    assert lancedb_store.count() == 1

    # Remaining record is safe_record
    res = lancedb_store.search([0.0, 0.0, 0.0, 1.0], top_k=5)
    assert len(res) == 1
    assert res[0]["chunk_id"] == "safe_record"


def test_bug5_lancedb_filters_and_error_handling(lancedb_store):
    """Bug #5: LanceDB supports file_id filtering and rejects unsupported filters."""
    records = [
        {"chunk_id": "c1", "file_id": "f1", "embedding": [1.0, 0.0, 0.0, 0.0]},
        {"chunk_id": "c2", "file_id": "f2", "embedding": [1.0, 0.0, 0.0, 0.0]},
    ]
    lancedb_store.upsert_vectors(records)

    # Valid file_id filter
    res = lancedb_store.search([1.0, 0.0, 0.0, 0.0], top_k=5, filters={"file_id": "f1"})
    assert len(res) == 1
    assert res[0]["chunk_id"] == "c1"

    # Unsupported filter raises ValueError
    with pytest.raises(ValueError) as excinfo:
        lancedb_store.search([1.0, 0.0, 0.0, 0.0], top_k=5, filters={"extension": ".pdf"})
    assert "only supports 'file_id' filter" in str(excinfo.value)
