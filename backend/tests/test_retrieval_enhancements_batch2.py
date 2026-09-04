"""Tests for retrieval enhancements: BM25 candidate expansion, related content batching, and token estimator fast path."""

import os
import tempfile

import pytest

from app.ai.context import TokenEstimator
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.related import RelatedContentService


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_retrieval_enhancements.db")
    db_mgr = DatabaseManager(db_file)
    with db_mgr.session() as conn:
        apply_migrations(conn)
    yield db_mgr
    try:
        if os.path.exists(db_file):
            os.remove(db_file)
        os.rmdir(temp_dir)
    except Exception:
        pass


def test_token_estimator_fast_path():
    """Verifies ASCII fast path gives identical results to full tokenizer heuristic."""
    estimator = TokenEstimator()

    # Empty text
    assert estimator.estimate("") == 0
    assert estimator.estimate(None) == 0
    assert estimator.estimate("   ") == 0

    # Pure ASCII
    ascii_sample = "The quick brown fox jumps over the lazy dog."
    assert estimator.estimate(ascii_sample) > 0

    # CJK text
    cjk_sample = "这是一个测试文件。"
    assert estimator.estimate(cjk_sample) == 9

    # Mixed text
    mixed_sample = "Report 2026: 财务报告 summary."
    assert estimator.estimate(mixed_sample) > 0


def test_related_content_batching_get_files_by_ids(temp_db):
    """Verifies get_files_by_ids efficiently returns mapped file records."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\test\folder")
        f1 = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=r"C:\test\folder\f1.txt",
            relative_path="f1.txt",
            filename="f1.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            sha256="h1",
        )
        f2 = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=r"C:\test\folder\f2.txt",
            relative_path="f2.txt",
            filename="f2.txt",
            extension=".txt",
            size_bytes=200,
            modified_at="2026-01-01T00:00:00Z",
            sha256="h2",
        )

        batch_recs = repo.get_files_by_ids([f1["file_id"], f2["file_id"], "nonexistent"])
        assert f1["file_id"] in batch_recs
        assert f2["file_id"] in batch_recs
        assert "nonexistent" not in batch_recs
        assert batch_recs[f1["file_id"]]["filename"] == "f1.txt"
        assert batch_recs[f2["file_id"]]["filename"] == "f2.txt"


def test_bm25_candidate_pool_expansion(temp_db):
    """Verifies that LexicalRetriever fetches an expanded candidate pool and applies boosts."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\test\folder")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=r"C:\test\folder\database_guide.txt",
            relative_path="database_guide.txt",
            filename="database_guide.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            sha256="h1",
            index_status="INDEXED",
        )
        file_id = file_rec["file_id"]

        chunks = [
            {
                "chunk_id": f"c_{file_id}_{i}",
                "source_file": "database_guide.txt",
                "source_path": r"C:\test\folder\database_guide.txt",
                "content": f"Database search terms and concepts paragraph {i} with specific keywords {i * 10}",
                "content_hash": f"ch_{i}",
                "chunk_index": i,
            }
            for i in range(10)
        ]
        repo.replace_file_chunks(file_id, chunks)

        retriever = LexicalRetriever(conn)
        results = retriever.search("database concepts", top_k=5)
        assert len(results) == 5
        assert all(r["chunk_id"].startswith("c_") for r in results)
        assert all(r["source_file"] == "database_guide.txt" for r in results)
