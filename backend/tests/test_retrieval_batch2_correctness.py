"""Test suite for Pre-Phase-4 Bug Fix Batch 2:
Retrieval Correctness, Ranking Calibration, Query Quality, and Snippet Hygiene.

Covers:
- Bug #3: Dense Filtered Retrieval Completeness (SqliteVecStore adaptive candidate expansion)
- Bug #7: Filename/Stem Boost Calibration and Adversarial Ranking Tests
- Bug #8: Query Token and Phrase Deduplication
- Bug #9: Multi-extension Filename Stem Handling
- Bug #10: Word-Boundary Snippet Matching and Technical Identifiers
"""

import os
import sqlite3
import tempfile
from typing import Any, Dict, List
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.provenance import ChunkProvenance
from app.retrieval.hybrid import HybridRetriever, generate_real_snippet
from app.retrieval.lexical import LexicalRetriever, extract_filename_stems
from app.retrieval.normalizer import normalize_query
from app.retrieval.vector_store import SqliteVecStore


# ===========================================================================
# BUG #3: Dense Filtered Retrieval Completeness Tests
# ===========================================================================

def test_bug3_dense_filtered_retrieval_finds_candidates_beyond_initial_pool():
    """Bug #3: Valid filtered candidates beyond the initial top_k*5 candidate pool
    must be retrieved adaptively until top_k filtered items are found."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_bug3_vec.db")
        db = DatabaseManager(db_path)
        with db.session() as conn:
            apply_migrations(conn)
            vec_store = SqliteVecStore(conn, dimension=4)
            repo = Repository(conn)
            dir_a = os.path.join(tmp_dir, "folder_a")
            dir_b = os.path.join(tmp_dir, "folder_b")
            os.makedirs(dir_a, exist_ok=True)
            os.makedirs(dir_b, exist_ok=True)
            folder_a = repo.create_folder(dir_a)["folder_id"]
            folder_b = repo.create_folder(dir_b)["folder_id"]

            vec_records = []
            # 30 records in folder_a with angle closer to query [1, 0, 0, 0]
            for i in range(30):
                fid = f"fa_{i}"
                cid = f"ca_{i}"
                f_path = os.path.join(dir_a, f"file_{i}.txt")
                with open(f_path, "w") as f:
                    f.write(f"content {i}")
                repo.upsert_file(folder_a, f_path, f"file_{i}.txt", f"file_{i}.txt", ".txt", 10, "2026-09-01T00:00:00Z", file_id=fid)
                chunk = ChunkProvenance(cid, fid, f"file_{i}.txt", f_path, None, None, None, None, 1, 1, 0, 10, f"h_{i}", 0, "p", "1.0", "1.0", f"content {i}", "text", 2)
                repo.replace_file_chunks(fid, [chunk])
                vec_records.append({"chunk_id": cid, "file_id": fid, "embedding": [0.9, 0.1, float(i) / 1000.0, 0.0]})

            # 10 records in folder_b with angle further from query [1, 0, 0, 0]
            for i in range(10):
                fid = f"fb_{i}"
                cid = f"cb_{i}"
                f_path = os.path.join(dir_b, f"bfile_{i}.txt")
                with open(f_path, "w") as f:
                    f.write(f"bcontent {i}")
                repo.upsert_file(folder_b, f_path, f"bfile_{i}.txt", f"bfile_{i}.txt", ".txt", 10, "2026-09-01T00:00:00Z", file_id=fid)
                chunk = ChunkProvenance(cid, fid, f"bfile_{i}.txt", f_path, None, None, None, None, 1, 1, 0, 10, f"hb_{i}", 0, "p", "1.0", "1.0", f"bcontent {i}", "text", 2)
                repo.replace_file_chunks(fid, [chunk])
                vec_records.append({"chunk_id": cid, "file_id": fid, "embedding": [0.1, 0.9, float(i) / 1000.0, 0.0]})

            vec_store.upsert_vectors(vec_records)

            # Search folder_b with top_k = 5.
            # All 30 folder_a records rank higher in raw cosine similarity.
            # Under old fetch_k = 5*5 = 25, 0 results were returned.
            # Adaptive search must return all 5 requested items from folder_b.
            results = vec_store.search([1.0, 0.0, 0.0, 0.0], top_k=5, filters={"folder_id": folder_b})
            assert len(results) == 5, f"Expected 5 filtered candidates, got {len(results)}"
            for r in results:
                assert r["file_id"].startswith("fb_"), f"Unexpected result file_id: {r['file_id']}"


def test_bug3_restrictive_filter_returns_zero_without_falsely_degrading():
    """Bug #3: Restrictive filters matching 0 records return empty list cleanly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_bug3_zero.db")
        db = DatabaseManager(db_path)
        with db.session() as conn:
            apply_migrations(conn)
            vec_store = SqliteVecStore(conn, dimension=4)
            repo = Repository(conn)
            folder = repo.create_folder(tmp_dir)["folder_id"]

            f_path = os.path.join(tmp_dir, "doc.txt")
            with open(f_path, "w") as f:
                f.write("test doc")
            repo.upsert_file(folder, f_path, "doc.txt", "doc.txt", ".txt", 8, "2026-09-01T00:00:00Z", file_id="f1")
            chunk = ChunkProvenance("c1", "f1", "doc.txt", f_path, None, None, None, None, 1, 1, 0, 8, "h1", 0, "p", "1.0", "1.0", "test doc", "text", 2)
            repo.replace_file_chunks("f1", [chunk])
            vec_store.upsert_vectors([{"chunk_id": "c1", "file_id": "f1", "embedding": [1.0, 0.0, 0.0, 0.0]}])

            # Filter for a non-existent extension
            results = vec_store.search([1.0, 0.0, 0.0, 0.0], top_k=5, filters={"extension": ".pdf"})
            assert results == []


# ===========================================================================
# BUG #8: Query Token Deduplication Tests
# ===========================================================================

def test_bug8_query_token_deduplication_ordinary_and_technical():
    """Bug #8: Tokens must be deduplicated in first-seen order."""
    nq1 = normalize_query("test test test")
    assert nq1.tokens == ["test"]
    assert nq1.fts5_query == '"test"*'

    nq2 = normalize_query("FILEMIND FILEMIND alpha")
    assert nq2.tokens == ["FILEMIND", "alpha"]

    nq3 = normalize_query("SHA-256 SHA-256 sha-256")
    assert nq3.tokens == ["SHA-256"]

    nq4 = normalize_query("sqlite-vec sqlite-vec v1.0.0 v1.0.0")
    assert nq4.tokens == ["sqlite-vec", "v1.0.0"]


def test_bug8_query_phrase_deduplication_and_fts5_safety():
    """Bug #8: Quoted phrases must be deduplicated while preserving phrase data."""
    nq = normalize_query('"exact phrase" "exact phrase" single single')
    assert nq.phrases == ["exact phrase"]
    assert nq.tokens == ["exact", "phrase", "single"]
    assert '"exact phrase"' in nq.fts5_query
    assert '"single"*' in nq.fts5_query


# ===========================================================================
# BUG #9: Multi-extension Filename Stem Handling Tests
# ===========================================================================

@pytest.mark.parametrize(
    "filename,expected_direct,expected_root",
    [
        ("archive.tar.gz", "archive.tar", "archive"),
        ("archive.tar", "archive", "archive"),
        ("archive", "archive", "archive"),
        ("file.txt", "file", "file"),
        ("README", "README", "README"),
        ("report.final.pdf", "report.final", "report"),
        ("backup.2026.08.tar.gz", "backup.2026.08.tar", "backup"),
    ],
)
def test_bug9_extract_filename_stems(filename, expected_direct, expected_root):
    """Bug #9: extract_filename_stems must extract direct stem and root stem consistently."""
    direct, root = extract_filename_stems(filename)
    assert direct == expected_direct
    assert root == expected_root


# ===========================================================================
# BUG #10: Word-Boundary Snippet Matching Tests
# ===========================================================================

def test_bug10_snippet_prefers_word_boundary_over_substring():
    """Bug #10: Snippet anchoring must prefer whole word matches over interior substrings."""
    content = "The category of advanced algorithms is broad. In a quiet corner, a cat was resting peacefully on the porch."
    # 'cat' occurs as a substring inside 'category' at pos 4, and as a whole word at pos 68.
    snippet = generate_real_snippet(content, ["cat"], max_chars=60)
    assert "resting peacefully" in snippet or "cat was resting" in snippet
    assert not snippet.startswith("The category")


def test_bug10_snippet_technical_identifiers_and_boundaries():
    """Bug #10: Snippet boundary matching handles hyphens, underscores, and dots."""
    content1 = "System logs initialized. Verified integrity using SHA-256 checksum algorithm successfully."
    s1 = generate_real_snippet(content1, ["SHA-256"], max_chars=60)
    assert "SHA-256" in s1

    content2 = "Event audit recorded. Tag FILEMIND_PRACTICAL_ALPHA_7319 was attached to the deployment unit."
    s2 = generate_real_snippet(content2, ["FILEMIND_PRACTICAL"], max_chars=60)
    assert "FILEMIND_PRACTICAL_ALPHA_7319" in s2

    content3 = "Database storage initialized with sqlite-vec extension for high throughput."
    s3 = generate_real_snippet(content3, ["sqlite-vec"], max_chars=60)
    assert "sqlite-vec" in s3


def test_bug10_snippet_substring_fallback_when_no_boundary_match():
    """Bug #10: When no word-boundary match exists, fallback to substring match gracefully."""
    content = "UnsegmentedStreamXyzStreamData processed."
    snippet = generate_real_snippet(content, ["Xyz"], max_chars=30)
    assert "Xyz" in snippet


def test_bug10_snippet_no_match_falls_back_to_beginning():
    """Bug #10: When query tokens are not in content, fall back to start with ellipsis."""
    content = "This is a document about planetary motion and celestial mechanics across galaxies."
    snippet = generate_real_snippet(content, ["quantum"], max_chars=40)
    assert snippet.startswith("This is a document")
    assert snippet.endswith("...")


# ===========================================================================
# BUG #7: Adversarial Ranking Tests for RRF Filename/Stem Boosts
# ===========================================================================

class MockVectorStore:
    def __init__(self, dense_results: List[Dict[str, Any]]):
        self._results = dense_results

    def search(self, *args, **kwargs):
        return self._results


class MockLexicalRetriever:
    def __init__(self, lex_results: List[Dict[str, Any]]):
        self._results = lex_results

    def search(self, *args, **kwargs):
        return self._results


class MockEmbeddingEngine:
    def __init__(self):
        self.dimension = 4

    def embed_query(self, query_text: str):
        return [1.0, 0.0, 0.0, 0.0]


def test_bug7_adversarial_1_exact_filename_vs_strong_dense_match():
    """Bug #7 Case 1: A strong semantic dense match (rank 1 dense, rank 1 lexical)
    must rank above an exact filename match that has only a weak rank 30+ presence."""
    conn = sqlite3.connect(":memory:")

    # Build 30 filler candidates between c_content and c_filename
    dense_candidates = [
        {"chunk_id": "c_content", "file_id": "f_content", "score": 0.95, "source_file": "architecture_guide.md", "source_path": "/docs/guide.md", "content": "Sample processing guide.", "content_hash": "h1"}
    ]
    lex_candidates = [
        {"chunk_id": "c_content", "file_id": "f_content", "score": 18.0, "source_file": "architecture_guide.md", "source_path": "/docs/guide.md", "content": "Sample processing guide.", "content_hash": "h1"}
    ]

    for i in range(1, 30):
        dense_candidates.append({
            "chunk_id": f"c_filler_{i}", "file_id": f"f_filler_{i}", "score": 0.95 - (i * 0.01),
            "source_file": f"filler_{i}.txt", "source_path": f"/docs/filler_{i}.txt",
            "content": f"Filler content {i}.", "content_hash": f"hf_{i}"
        })
        lex_candidates.append({
            "chunk_id": f"c_filler_{i}", "file_id": f"f_filler_{i}", "score": 18.0 - (i * 0.2),
            "source_file": f"filler_{i}.txt", "source_path": f"/docs/filler_{i}.txt",
            "content": f"Filler content {i}.", "content_hash": f"hf_{i}"
        })

    dense_candidates.append({"chunk_id": "c_filename", "file_id": "f_filename", "score": 0.10, "source_file": "sample.txt", "source_path": "/docs/sample.txt", "content": "Irrelevant random notes.", "content_hash": "h2"})
    lex_candidates.append({"chunk_id": "c_filename", "file_id": "f_filename", "score": 2.0, "source_file": "sample.txt", "source_path": "/docs/sample.txt", "content": "Irrelevant random notes.", "content_hash": "h2"})

    retriever = HybridRetriever(
        conn,
        embedding_engine=MockEmbeddingEngine(),
        vector_store=MockVectorStore(dense_candidates),
    )
    retriever.lexical_retriever = MockLexicalRetriever(lex_candidates)

    result = retriever.search("sample", top_k=2)
    results = result["results"]
    assert len(results) == 2
    # Under old +0.05 boost, c_filename at rank 30 would jump to #1 with score ~0.071 vs c_content 0.0328.
    # Under calibrated +0.0050 boost, c_content correctly stays at #1 with score 0.0328 vs c_filename 0.0269.
    assert results[0]["chunk_id"] == "c_content", (
        f"Expected c_content to rank #1, but {results[0]['chunk_id']} was #1. Boost overpowered content!"
    )


def test_bug7_adversarial_2_exact_filename_vs_strong_bm25_content_match():
    """Bug #7 Case 2: A document with strong dual-arm rank 1 content match must
    rank above a document whose only merit is matching the filename at rank 20."""
    conn = sqlite3.connect(":memory:")
    retriever = HybridRetriever(
        conn,
        embedding_engine=MockEmbeddingEngine(),
        vector_store=MockVectorStore([
            {"chunk_id": "c_content", "file_id": "f_content", "score": 0.92, "source_file": "deep_analysis.pdf", "source_path": "/docs/deep.pdf", "content": "Testing methodology.", "content_hash": "h1"},
        ]),
    )
    lex_candidates = [
        {"chunk_id": "c_content", "file_id": "f_content", "score": 25.0, "source_file": "deep_analysis.pdf", "source_path": "/docs/deep.pdf", "content": "Testing methodology.", "content_hash": "h1"},
    ]
    for i in range(1, 20):
        lex_candidates.append({
            "chunk_id": f"c_fill_{i}", "file_id": f"f_fill_{i}", "score": 25.0 - (i * 0.8),
            "source_file": f"filler_{i}.txt", "source_path": f"/docs/filler_{i}.txt",
            "content": f"Filler test content {i}.", "content_hash": f"hf_{i}"
        })
    lex_candidates.append({"chunk_id": "c_filename", "file_id": "f_filename", "score": 3.0, "source_file": "test.txt", "source_path": "/docs/test.txt", "content": "Unrelated line.", "content_hash": "h2"})

    retriever.lexical_retriever = MockLexicalRetriever(lex_candidates)

    result = retriever.search("test", top_k=2)
    results = result["results"]
    # c_content (rank 1 dense + rank 1 lexical = 0.0328) > c_filename (rank 2 lexical = 0.0161 + 0.0050 = 0.0211)
    assert results[0]["chunk_id"] == "c_content"


def test_bug7_adversarial_3_exact_filename_plus_strong_content_match():
    """Bug #7 Case 3: Exact filename match WITH strong content match ranks #1."""
    conn = sqlite3.connect(":memory:")
    retriever = HybridRetriever(
        conn,
        embedding_engine=MockEmbeddingEngine(),
        vector_store=MockVectorStore([
            {"chunk_id": "c_target", "file_id": "f_target", "score": 0.90, "source_file": "sample.txt", "source_path": "/docs/sample.txt", "content": "Sample file content.", "content_hash": "h1"},
            {"chunk_id": "c_other", "file_id": "f_other", "score": 0.89, "source_file": "other.txt", "source_path": "/docs/other.txt", "content": "Sample file reference.", "content_hash": "h2"},
        ]),
    )
    retriever.lexical_retriever = MockLexicalRetriever([
        {"chunk_id": "c_target", "file_id": "f_target", "score": 15.0, "source_file": "sample.txt", "source_path": "/docs/sample.txt", "content": "Sample file content.", "content_hash": "h1"},
        {"chunk_id": "c_other", "file_id": "f_other", "score": 14.5, "source_file": "other.txt", "source_path": "/docs/other.txt", "content": "Sample file reference.", "content_hash": "h2"},
    ])

    result = retriever.search("sample", top_k=2)
    results = result["results"]
    assert results[0]["chunk_id"] == "c_target"


def test_bug7_adversarial_4_partial_filename_vs_unrelated_content_match():
    """Bug #7 Case 4: Partial filename token match receives safe modest boost."""
    conn = sqlite3.connect(":memory:")
    retriever = HybridRetriever(
        conn,
        embedding_engine=MockEmbeddingEngine(),
        vector_store=MockVectorStore([
            {"chunk_id": "c1", "file_id": "f1", "score": 0.85, "source_file": "FILEMIND_PRACTICAL_ALPHA.txt", "source_path": "/p.txt", "content": "alpha notes", "content_hash": "h1"},
            {"chunk_id": "c2", "file_id": "f2", "score": 0.84, "source_file": "unrelated.txt", "source_path": "/u.txt", "content": "practical test", "content_hash": "h2"},
        ]),
    )
    retriever.lexical_retriever = MockLexicalRetriever([
        {"chunk_id": "c1", "file_id": "f1", "score": 10.0, "source_file": "FILEMIND_PRACTICAL_ALPHA.txt", "source_path": "/p.txt", "content": "alpha notes", "content_hash": "h1"},
        {"chunk_id": "c2", "file_id": "f2", "score": 9.8, "source_file": "unrelated.txt", "source_path": "/u.txt", "content": "practical test", "content_hash": "h2"},
    ])

    result = retriever.search("practical", top_k=2)
    results = result["results"]
    assert results[0]["chunk_id"] == "c1"


def test_bug7_adversarial_5_weak_filename_in_single_retrieval_arm():
    """Bug #7 Case 5: A weak filename candidate (rank 25 in lexical only)
    must NOT overtake a strong dual-arm rank-1 result."""
    conn = sqlite3.connect(":memory:")

    dense_candidates = [
        {"chunk_id": "c_dual", "file_id": "f_dual", "score": 0.90, "source_file": "guide.txt", "source_path": "/g.txt", "content": "comprehensive architecture notes", "content_hash": "h1"},
    ]
    lex_candidates = [
        {"chunk_id": "c_dual", "file_id": "f_dual", "score": 20.0, "source_file": "guide.txt", "source_path": "/g.txt", "content": "comprehensive architecture notes", "content_hash": "h1"},
    ]
    for i in range(1, 25):
        lex_candidates.append({
            "chunk_id": f"c_fill_{i}", "file_id": f"f_fill_{i}", "score": 20.0 - (i * 0.5),
            "source_file": f"filler_{i}.txt", "source_path": f"/docs/filler_{i}.txt",
            "content": f"Filler notes {i}.", "content_hash": f"hf_{i}"
        })
    lex_candidates.append({
        "chunk_id": "c_name_only", "file_id": "f_name_only", "score": 3.0,
        "source_file": "notes.md", "source_path": "/n.md", "content": "unrelated", "content_hash": "h2"
    })

    retriever = HybridRetriever(
        conn,
        embedding_engine=MockEmbeddingEngine(),
        vector_store=MockVectorStore(dense_candidates),
    )
    retriever.lexical_retriever = MockLexicalRetriever(lex_candidates)

    result = retriever.search("notes", top_k=2)
    results = result["results"]
    # c_dual has rank 1 in lexical + rank 1 in dense (0.0328)
    # c_name_only has rank 26 in lexical (1/86 + 0.0180 = 0.0296)
    # Dual arm rank 1 wins over weak tail filename candidate
    assert results[0]["chunk_id"] == "c_dual"


def test_bug7_adversarial_6_filename_in_both_retrieval_arms():
    """Bug #7 Case 6: Filename match present in both retrieval arms decisively ranks #1."""
    conn = sqlite3.connect(":memory:")
    retriever = HybridRetriever(
        conn,
        embedding_engine=MockEmbeddingEngine(),
        vector_store=MockVectorStore([
            {"chunk_id": "c_both", "file_id": "f_both", "score": 0.95, "source_file": "notes.md", "source_path": "/n.md", "content": "daily notes", "content_hash": "h1"},
            {"chunk_id": "c_other", "file_id": "f_other", "score": 0.80, "source_file": "other.md", "source_path": "/o.md", "content": "some notes", "content_hash": "h2"},
        ]),
    )
    retriever.lexical_retriever = MockLexicalRetriever([
        {"chunk_id": "c_both", "file_id": "f_both", "score": 15.0, "source_file": "notes.md", "source_path": "/n.md", "content": "daily notes", "content_hash": "h1"},
        {"chunk_id": "c_other", "file_id": "f_other", "score": 10.0, "source_file": "other.md", "source_path": "/o.md", "content": "some notes", "content_hash": "h2"},
    ])

    result = retriever.search("notes", top_k=2)
    results = result["results"]
    assert results[0]["chunk_id"] == "c_both"
    assert results[0]["score"] > results[1]["score"]


def test_bug7_exact_stem_discovery_restores_intended_filename_priority():
    """Bug #7: Exact stem queries (sample -> sample.txt, test -> test.txt)
    rank the exact filename match above a document that merely has incidental
    dense semantic similarity."""
    conn = sqlite3.connect(":memory:")
    # c_dense_only has high dense similarity (e.g. lecture slides on 'sampling') but ranks #5 in lexical
    # c_exact_file is 'sample.txt' with exact stem match and rank #1 in lexical
    retriever = HybridRetriever(
        conn,
        embedding_engine=MockEmbeddingEngine(),
        vector_store=MockVectorStore([
            {"chunk_id": "c_dense_only", "file_id": "f_dense", "score": 0.95, "source_file": "Copy of WEEK 04.pdf", "source_path": "/doc.pdf", "content": "sampling distributions", "content_hash": "h1"},
        ]),
    )
    retriever.lexical_retriever = MockLexicalRetriever([
        {"chunk_id": "c_exact_file", "file_id": "f_exact", "score": 15.0, "source_file": "sample.txt", "source_path": "/sample.txt", "content": "sample verification test", "content_hash": "h2"},
        {"chunk_id": "c_dense_only", "file_id": "f_dense", "score": 10.0, "source_file": "Copy of WEEK 04.pdf", "source_path": "/doc.pdf", "content": "sampling distributions", "content_hash": "h1"},
    ])

    result = retriever.search("sample", top_k=2)
    results = result["results"]
    assert len(results) == 2
    # c_exact_file: rank 1 lex (0.01639) + 0.0180 = 0.03439
    # c_dense_only: rank 1 dense (0.01639) + rank 2 lex (0.01613) = 0.03252
    # c_exact_file must rank #1
    assert results[0]["chunk_id"] == "c_exact_file"
    assert results[0]["source_file"] == "sample.txt"

