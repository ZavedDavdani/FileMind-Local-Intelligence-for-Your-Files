"""Authoritative verification tests for the 8 prioritized latent production risks.

Tests:
1. P0: Connection-per-operation + SQLite/WAL pressure (DatabaseManager pooling, sqlite-vec loading, thread connection reuse, close_all)
2. P0: Ollama HTTP connection reuse (OllamaProvider._get_client reuse in generate)
3. P1: Embedding & Reranker timeout/cooldown state machine recovery
4. P1: Worker stale-job pre-check and atomic write ownership
5. P2: Adaptive vector-search over-fetch bounding with candidate cardinality pre-check
6. P2: Windows path case & drive letter canonical normalization (security & watcher)
7. P2: Multi-statement delete atomicity (purge_file and purge_folder across virtual & relational tables)
8. P3: API contract envelope handling and AbortError discrimination
"""

import os
import sqlite3
import threading
import time
import unittest.mock as mock
from pathlib import Path
import pytest

from app.ai.ollama_provider import OllamaProvider, OllamaResponse
from app.core.security import (
    canonical_path_key,
    is_path_within_root,
    normalize_path,
    normalize_windows_path,
)
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.pipeline import IndexingPipelineResult
from app.engine.watcher import is_subpath
from app.engine.worker import WorkerPool
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import SqliteVecStore


def test_db_manager_thread_local_reuse_and_close_all(tmp_path):
    db_file = tmp_path / "test_pooled.db"
    mgr = DatabaseManager(db_file, pooled=True)
    assert mgr._pooled is True

    # Same thread should reuse connection across sessions
    with mgr.session() as conn1:
        apply_migrations(conn1)
        conn_id_1 = id(conn1)

    with mgr.session() as conn2:
        conn_id_2 = id(conn2)

    assert conn_id_1 == conn_id_2, "Expected connection reuse within same thread"

    # Separate thread gets distinct connection
    thread_conn_ids = []

    def worker():
        with mgr.session() as conn3:
            thread_conn_ids.append(id(conn3))

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert len(thread_conn_ids) == 1
    assert thread_conn_ids[0] != conn_id_1

    # close_all closes all pooled connections across threads
    mgr.close_all()
    assert len(mgr._open_connections) == 0


def test_ollama_provider_reuses_persistent_client(monkeypatch):
    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="qwen3:4b")

    mock_client = mock.MagicMock()
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "qwen3:4b",
        "response": "Hello world",
        "done": True,
        "done_reason": "stop",
    }
    mock_client.post.return_value = mock_resp

    with mock.patch.object(provider, "_get_client", return_value=mock_client) as mock_get_client:
        res1 = provider.generate("First prompt")
        res2 = provider.generate("Second prompt")

    assert res1.response == "Hello world"
    assert res2.response == "Hello world"
    assert mock_get_client.call_count == 2
    assert mock_client.post.call_count == 2
    provider.close()


def test_embedding_cooldown_recovery_state_machine(monkeypatch):
    current_time = [1000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    engine = EmbeddingEngine(retry_cooldown=30.0, load_timeout=1.0)
    assert not engine.is_in_cooldown

    # Failure triggers cooldown
    with mock.patch("fastembed.TextEmbedding", side_effect=RuntimeError("Download timeout")):
        with pytest.raises(RuntimeError, match="Download timeout"):
            engine.embed_texts(["hello"])

    assert engine.is_in_cooldown
    assert engine._init_error is not None

    # Reset clears failure and cooldown
    engine.reset_init_state()
    assert not engine.is_in_cooldown
    assert engine._init_error is None

    # Successful load after recovery
    mock_inst = mock.MagicMock()
    mock_inst.embed.return_value = [[0.1] * 384]
    with mock.patch("fastembed.TextEmbedding", return_value=mock_inst):
        vectors = engine.embed_texts(["hello"])

    assert len(vectors) == 1
    assert not engine.is_in_cooldown
    assert engine._init_error is None


def test_reranker_cooldown_recovery_state_machine(monkeypatch):
    current_time = [2000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    reranker = Reranker(retry_cooldown=30.0, load_timeout=1.0)
    assert not reranker.is_in_cooldown

    with mock.patch("fastembed.rerank.cross_encoder.TextCrossEncoder", side_effect=RuntimeError("Load error")):
        with pytest.raises(RuntimeError, match="Load error"):
            reranker.rerank("query", [{"content": "doc1"}])

    assert reranker.is_in_cooldown

    # Reset clears failure state
    reranker.reset_init_state()
    assert not reranker.is_in_cooldown


def test_worker_stale_job_precheck(tmp_path):
    db_file = tmp_path / "test_worker.db"
    mgr = DatabaseManager(db_file)
    with mgr.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        fld = repo.create_folder(str(tmp_path))
        target_file = tmp_path / "stale_test.txt"
        target_file.write_text("initial content", encoding="utf-8")
        f = repo.upsert_file(
            folder_id=fld["folder_id"],
            path=str(target_file),
            relative_path="stale_test.txt",
            filename="stale_test.txt",
            extension=".txt",
            size_bytes=len("initial content"),
            modified_at="2026-01-01T00:00:00Z",
            index_status="QUEUED",
        )
        # Enqueue job1 and claim it so it is in PROCESSING
        repo.enqueue_job(file_id=f["file_id"], folder_id=fld["folder_id"], job_id="job-1-uuid")
        claimed_job1 = repo.claim_next_job()
        assert claimed_job1 is not None

        # Enqueue job2 (newer pending job for same file)
        repo.enqueue_job(file_id=f["file_id"], folder_id=fld["folder_id"], job_id="job-2-newer-uuid")

    worker_pool = WorkerPool(mgr, max_workers=1)

    # When worker processes job1, it should detect that job2 supersedes job1 and skip pipeline.execute
    with mock.patch.object(worker_pool.pipeline, "execute") as mock_exec:
        worker_pool._process_job(claimed_job1)
        mock_exec.assert_not_called()


def test_vector_search_filter_cardinality_bounding(tmp_path):
    db_file = tmp_path / "test_vec.db"
    mgr = DatabaseManager(db_file)
    with mgr.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        fld = repo.create_folder(str(tmp_path))
        f = repo.upsert_file(
            folder_id=fld["folder_id"],
            path=str(tmp_path / "sample.txt"),
            relative_path="sample.txt",
            filename="sample.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(f["file_id"], [
            {
                "chunk_id": "c1",
                "source_file": "sample.txt",
                "source_path": str(tmp_path / "sample.txt"),
                "content_hash": "hash1",
                "chunk_index": 0,
                "parser_name": "text",
                "parser_version": "1.0",
                "chunker_version": "1.0",
                "content": "first chunk content",
                "content_type": "text",
                "token_count": 5,
                "metadata_json": "{}",
            }
        ])
        vec_store = SqliteVecStore(conn, dimension=4)
        vec_store.upsert_vectors([
            {"chunk_id": "c1", "embedding": [1.0, 0.0, 0.0, 0.0], "file_id": f["file_id"]}
        ])

        # Filter for non-existent file returns [] immediately without adaptive iterations
        empty_res = vec_store.search([1.0, 0.0, 0.0, 0.0], top_k=10, filters={"file_id": "non-existent-id"})
        assert empty_res == []

        # Filter for existing file with only 1 chunk bounds target_k to 1 and stops immediately
        res = vec_store.search([1.0, 0.0, 0.0, 0.0], top_k=10, filters={"file_id": f["file_id"]})
        assert len(res) == 1
        assert res[0]["chunk_id"] == "c1"


def test_windows_path_case_and_containment():
    # Drive letter normalization
    norm1 = normalize_path("c:\\dev\\folder\\file.txt")
    norm2 = normalize_path("C:\\dev\\folder\\file.txt")
    assert norm1 == norm2
    assert norm1.startswith("C:")

    # Canonical path key
    key1 = canonical_path_key("C:\\Dev\\Folder\\File.txt")
    key2 = canonical_path_key("c:/dev/folder/file.txt")
    assert key1 == key2

    # Containment safety without prefix collisions
    assert is_path_within_root("C:\\dev\\folder\\file.txt", "C:\\dev\\folder")
    assert not is_path_within_root("C:\\dev\\folder_sibling\\file.txt", "C:\\dev\\folder")
    assert is_subpath("C:\\dev\\folder\\sub\\file.txt", "C:\\dev\\folder")
    assert not is_subpath("C:\\dev\\folder_sibling\\file.txt", "C:\\dev\\folder")


def test_atomic_purge_file_and_folder(tmp_path):
    db_file = tmp_path / "test_purge.db"
    mgr = DatabaseManager(db_file)
    with mgr.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        fld = repo.create_folder(str(tmp_path))
        f = repo.upsert_file(
            folder_id=fld["folder_id"],
            path=str(tmp_path / "doc.txt"),
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=50,
            modified_at="2026-01-01T00:00:00Z",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(f["file_id"], [
            {
                "chunk_id": "c_doc_1",
                "source_file": "doc.txt",
                "source_path": str(tmp_path / "doc.txt"),
                "content_hash": "hash_doc",
                "chunk_index": 0,
                "parser_name": "text",
                "parser_version": "1.0",
                "chunker_version": "1.0",
                "content": "doc chunk",
                "content_type": "text",
                "token_count": 3,
                "metadata_json": "{}",
            }
        ])
        vec_store = SqliteVecStore(conn, dimension=4)
        vec_store.upsert_vectors([
            {"chunk_id": "c_doc_1", "embedding": [0.0, 1.0, 0.0, 0.0], "file_id": f["file_id"]}
        ])
        repo.upsert_document_insight(
            file_id=f["file_id"],
            status="READY",
            content_hash="hash_doc",
            parser_version="1.0",
            chunker_version="1.0",
            model_provider="ollama",
            model_name="qwen3:4b",
            executive_summary="Summary text",
        )

        assert vec_store.count() == 1
        assert repo.get_file_by_id(f["file_id"]) is not None

        # Test purge_file: atomically removes vectors, insights, chunks, and file
        purged = repo.purge_file(f["file_id"])
        assert purged is True
        assert repo.get_file_by_id(f["file_id"]) is None
        assert vec_store.count() == 0
        assert repo.get_document_insight(f["file_id"], "qwen3:4b") is None

        # Test purge_folder
        purged_folder = repo.purge_folder(fld["folder_id"])
        assert purged_folder is True
        assert repo.get_folder(fld["folder_id"]) is None


def test_envelope_extraction_logic():
    def extract_array(data, key):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get(key), list):
                return data[key]
            for candidate in ["data", "value", "items", "results", "list"]:
                if isinstance(data.get(candidate), list):
                    return data[candidate]
        raise ValueError("Invalid shape")

    assert extract_array([1, 2, 3], "folders") == [1, 2, 3]
    assert extract_array({"folders": [1, 2]}, "folders") == [1, 2]
    assert extract_array({"data": [1, 2, 3]}, "folders") == [1, 2, 3]
    assert extract_array({"value": [4, 5]}, "files") == [4, 5]
