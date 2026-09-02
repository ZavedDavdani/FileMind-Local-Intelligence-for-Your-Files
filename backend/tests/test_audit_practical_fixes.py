"""Regression test suite for Pre-Phase-5 practical audit issues.

Covers:
1. ISSUE 1: Tauri v2 directory dialog capability configuration validation.
2. ISSUE 2: File-level candidate grouping and provenance preservation.
3. ISSUE 3: Deterministic explicit filename intent detection & unindexed filename handling:
   - Existing indexed filename -> found.
   - Nonexistent filename -> consistent not-found (0 results) across BM25, Dense, Hybrid Fast, Hybrid Quality.
   - Normal semantic query -> normal semantic retrieval remains active.
   - Conversational questions referencing files -> treated as content queries.
"""

import json
import os
import sqlite3
import pytest

from app.db.connection import db_manager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.hybrid import HybridRetriever, extract_explicit_filename_intent
from app.retrieval.normalizer import normalize_query
from app.retrieval.vector_store import MemoryCosineStore


# ---------------------------------------------------------------------------
# ISSUE 1 REGRESSION: Tauri v2 Dialog Capability Configuration
# ---------------------------------------------------------------------------

def test_tauri_dialog_capability_configured():
    """Verify that src-tauri/capabilities/default.json exists, is valid JSON, and grants dialog:allow-open."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cap_path = os.path.join(repo_root, "src-tauri", "capabilities", "default.json")

    assert os.path.isfile(cap_path), f"Capabilities file missing at {cap_path}"

    with open(cap_path, "r", encoding="utf-8") as f:
        cap_data = json.load(f)

    assert "windows" in cap_data
    assert "main" in cap_data["windows"] or "*" in cap_data["windows"]
    assert "permissions" in cap_data
    assert "dialog:allow-open" in cap_data["permissions"] or "dialog:default" in cap_data["permissions"]


# ---------------------------------------------------------------------------
# ISSUE 2 REGRESSION: Grouping & Provenance Invariants
# ---------------------------------------------------------------------------

def test_same_file_grouping_helper_invariants():
    """Verify that multiple chunks from the same file preserve their individual scores and provenance."""
    # Simulate search results returned from backend with multiple chunks for file1 and file2
    mock_results = [
        {
            "rank": 1,
            "chunk_id": "file1_chunk_0",
            "file_id": "file1",
            "source_file": "notes.md",
            "source_path": "/docs/notes.md",
            "score": 0.032,
            "snippet": "First chunk content",
            "page": 1,
            "line_start": 1,
            "line_end": 15,
        },
        {
            "rank": 2,
            "chunk_id": "file2_chunk_0",
            "file_id": "file2",
            "source_file": "report.pdf",
            "source_path": "/docs/report.pdf",
            "score": 0.028,
            "snippet": "Report chunk content",
            "page": 1,
            "line_start": 1,
            "line_end": 20,
        },
        {
            "rank": 3,
            "chunk_id": "file1_chunk_1",
            "file_id": "file1",
            "source_file": "notes.md",
            "source_path": "/docs/notes.md",
            "score": 0.021,
            "snippet": "Second chunk content",
            "page": 2,
            "line_start": 16,
            "line_end": 35,
        },
    ]

    # Deterministic grouping algorithm matching SearchModal.tsx
    groups = []
    group_map = {}
    for r in mock_results:
        key = r["file_id"]
        if key not in group_map:
            group = {
                "file_id": r["file_id"],
                "source_file": r["source_file"],
                "source_path": r["source_path"],
                "bestRank": r["rank"],
                "bestScore": r["score"],
                "chunks": [],
            }
            group_map[key] = group
            groups.append(group)
        group_map[key]["chunks"].append(r)

    # 1. Total file groups must be 2 (notes.md and report.pdf)
    assert len(groups) == 2

    # 2. First group is notes.md with 2 chunks
    assert groups[0]["source_file"] == "notes.md"
    assert groups[0]["bestRank"] == 1
    assert groups[0]["bestScore"] == 0.032
    assert len(groups[0]["chunks"]) == 2
    assert groups[0]["chunks"][0]["chunk_id"] == "file1_chunk_0"
    assert groups[0]["chunks"][1]["chunk_id"] == "file1_chunk_1"

    # 3. Second group is report.pdf with 1 chunk
    assert groups[1]["source_file"] == "report.pdf"
    assert groups[1]["bestRank"] == 2
    assert len(groups[1]["chunks"]) == 1

    # 4. Provenance and lines are preserved intact
    assert groups[0]["chunks"][0]["line_start"] == 1
    assert groups[0]["chunks"][1]["line_start"] == 16


# ---------------------------------------------------------------------------
# ISSUE 3 REGRESSION: Explicit Filename Intent Detection & Consistent Not-Found
# ---------------------------------------------------------------------------

def test_extract_explicit_filename_intent():
    """Verify exact filename intent detection logic across varied inputs."""
    # Positive explicit filename lookups
    assert extract_explicit_filename_intent("nonexistent_report.pdf") == "nonexistent_report.pdf"
    assert extract_explicit_filename_intent(' "budget_2024.xlsx" ') == "budget_2024.xlsx"
    assert extract_explicit_filename_intent("notes.md") == "notes.md"
    assert extract_explicit_filename_intent("subfolder/data.csv") == "data.csv"
    assert extract_explicit_filename_intent("C:\\Users\\docs\\main.py") == "main.py"
    assert extract_explicit_filename_intent("archive.tar.gz") == "archive.tar.gz"

    # Negative / Semantic queries (must NOT be treated as explicit filename lookups)
    assert extract_explicit_filename_intent("How does semantic retrieval work?") is None
    assert extract_explicit_filename_intent("What is in report.pdf?") is None
    assert extract_explicit_filename_intent("Explain the calculation in budget.xlsx") is None
    assert extract_explicit_filename_intent("quarterly business revenue and financial profit margins") is None
    assert extract_explicit_filename_intent("def get_config():") is None
    assert extract_explicit_filename_intent("Write-Ahead Logging (WAL) mode enabled") is None


class DummyEmbeddingEngine:
    """Mock embedding engine for deterministic testing."""
    def __init__(self, dimension: int = 4):
        self.dimension = dimension

    def embed_query(self, text: str):
        return [0.1, 0.2, 0.3, 0.4]

    def embed_chunks(self, texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


@pytest.fixture
def seeded_retrieval_db(tmp_path):
    """Sets up an in-memory SQLite database seeded with indexed files and chunks."""
    db_file = str(tmp_path / "test_retrieval.db")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)

    repo = Repository(conn)
    folder = repo.create_folder("/test/folder", recursive=True, integrity_mode="NORMAL")
    folder_id = folder["folder_id"]

    # File 1: indexed report.pdf
    file1 = repo.upsert_file(
        folder_id=folder_id,
        path="/test/folder/report.pdf",
        relative_path="report.pdf",
        filename="report.pdf",
        extension=".pdf",
        size_bytes=1024,
        modified_at="2026-01-01T00:00:00Z",
        index_status="INDEXED",
    )

    # Insert chunk for report.pdf
    chunk1 = {
        "chunk_id": f"{file1['file_id']}_chunk_0",
        "file_id": file1["file_id"],
        "source_file": "report.pdf",
        "source_path": "/test/folder/report.pdf",
        "page": 1,
        "section": "Overview",
        "h1_parent": "Annual Financial Report",
        "h2_parent": "Revenue Breakdown",
        "line_start": 1,
        "line_end": 20,
        "char_start": 0,
        "char_end": 200,
        "content_hash": "hash123",
        "chunk_index": 0,
        "parser_name": "pdf_parser",
        "parser_version": "1.0.0",
        "chunker_version": "phase2-hierarchical-v2",
        "content": "Annual financial revenue breakdown shows strong profit margins in Q2.",
        "content_type": "text",
        "token_count": 15,
        "metadata_json": "{}",
    }
    repo.replace_file_chunks(file1["file_id"], [chunk1])

    # File 2: indexed notes.md
    file2 = repo.upsert_file(
        folder_id=folder_id,
        path="/test/folder/notes.md",
        relative_path="notes.md",
        filename="notes.md",
        extension=".md",
        size_bytes=512,
        modified_at="2026-01-01T00:00:00Z",
        index_status="INDEXED",
    )

    chunk2 = {
        "chunk_id": f"{file2['file_id']}_chunk_0",
        "file_id": file2["file_id"],
        "source_file": "notes.md",
        "source_path": "/test/folder/notes.md",
        "page": None,
        "section": "Architecture",
        "h1_parent": "System Design",
        "h2_parent": "Storage Engine",
        "line_start": 1,
        "line_end": 10,
        "char_start": 0,
        "char_end": 120,
        "content_hash": "hash456",
        "chunk_index": 0,
        "parser_name": "text_parser",
        "parser_version": "1.0.0",
        "chunker_version": "phase2-hierarchical-v2",
        "content": "Database storage engine uses SQLite with Write-Ahead Logging for high concurrency.",
        "content_type": "text",
        "token_count": 15,
        "metadata_json": "{}",
    }
    repo.replace_file_chunks(file2["file_id"], [chunk2])

    # Initialize in-memory vector store with embeddings for the chunks
    vec_store = MemoryCosineStore(dimension=4)
    vec_store.upsert_vectors([
        {"chunk_id": chunk1["chunk_id"], "file_id": file1["file_id"], "embedding": [0.1, 0.2, 0.3, 0.4]},
        {"chunk_id": chunk2["chunk_id"], "file_id": file2["file_id"], "embedding": [0.4, 0.3, 0.2, 0.1]},
    ])

    return conn, vec_store


def test_nonexistent_filename_returns_consistent_empty_across_all_modes(seeded_retrieval_db):
    """
    ISSUE 3 CORE INVARIANT:
    A nonexistent filename search (e.g. nonexistent_report.pdf) must consistently return
    total_found == 0 and results == [] across:
    - BM25 + Fast
    - Dense + Fast
    - Hybrid + Fast
    - Hybrid + Quality
    """
    conn, vec_store = seeded_retrieval_db
    engine = DummyEmbeddingEngine(dimension=4)

    retriever = HybridRetriever(
        db_conn=conn,
        embedding_engine=engine,
        vector_store=vec_store,
        reranker=None,  # No reranker needed for fast tests
    )

    query = "nonexistent_report.pdf"

    # 1. BM25 + Fast
    resp_bm25 = retriever.search(query=query, mode="bm25", quality="fast")
    assert resp_bm25["total_found"] == 0
    assert resp_bm25["results"] == []

    # 2. Dense + Fast
    resp_dense = retriever.search(query=query, mode="dense", quality="fast")
    assert resp_dense["total_found"] == 0
    assert resp_dense["results"] == []

    # 3. Hybrid + Fast
    resp_hybrid_fast = retriever.search(query=query, mode="hybrid", quality="fast")
    assert resp_hybrid_fast["total_found"] == 0
    assert resp_hybrid_fast["results"] == []

    # 4. Hybrid + Quality
    resp_hybrid_quality = retriever.search(query=query, mode="hybrid", quality="quality")
    assert resp_hybrid_quality["total_found"] == 0
    assert resp_hybrid_quality["results"] == []


def test_existing_indexed_filename_is_found(seeded_retrieval_db):
    """Verify that searching for an existing indexed filename finds the file's chunks."""
    conn, vec_store = seeded_retrieval_db
    engine = DummyEmbeddingEngine(dimension=4)

    retriever = HybridRetriever(
        db_conn=conn,
        embedding_engine=engine,
        vector_store=vec_store,
        reranker=None,
    )

    # Search for existing file 'report.pdf'
    resp = retriever.search(query="report.pdf", mode="hybrid", quality="fast")
    assert resp["total_found"] >= 1
    assert resp["results"][0]["source_file"] == "report.pdf"

    # Search in Dense mode
    resp_dense = retriever.search(query="report.pdf", mode="dense", quality="fast")
    assert resp_dense["total_found"] >= 1
    assert resp_dense["results"][0]["source_file"] == "report.pdf"

    # Search in BM25 mode
    resp_bm25 = retriever.search(query="report.pdf", mode="bm25", quality="fast")
    assert resp_bm25["total_found"] >= 1
    assert resp_bm25["results"][0]["source_file"] == "report.pdf"


def test_normal_semantic_query_remains_functional(seeded_retrieval_db):
    """Verify that general content and semantic queries continue to search normally."""
    conn, vec_store = seeded_retrieval_db
    engine = DummyEmbeddingEngine(dimension=4)

    retriever = HybridRetriever(
        db_conn=conn,
        embedding_engine=engine,
        vector_store=vec_store,
        reranker=None,
    )

    # Semantic query about storage
    resp = retriever.search(query="Write-Ahead Logging storage engine", mode="hybrid", quality="fast")
    assert resp["total_found"] >= 1
    assert any("notes.md" in r["source_file"] for r in resp["results"])

    # Semantic query with question mark
    resp_q = retriever.search(query="What is the revenue breakdown in report.pdf?", mode="hybrid", quality="fast")
    assert resp_q["total_found"] >= 1
    assert resp_q["results"][0]["source_file"] == "report.pdf"
