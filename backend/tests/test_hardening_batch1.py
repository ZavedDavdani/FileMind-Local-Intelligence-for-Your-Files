"""Regression tests for Stability and Integrity Hardening Batch 1."""

import os
import threading
import time
from unittest import mock

import pytest

from app.ai.generation import (
    GenerationConfig,
    GenerationStatus,
    GroundedGenerationResponse,
    GroundedGenerationService,
    ModelIdentity,
)
from app.ai.ollama_provider import (
    OllamaProvider,
    OllamaResponse,
)
from app.ai.prompt import (
    GroundedPrompt,
)
from app.ai.context import (
    BoundedContextPackage,
    BudgetAccounting,
    ContextItem,
    EvidenceStatus,
)
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import SqliteVecStore


def test_embedding_engine_failed_init_no_thread_leak():
    """Verifies that repeated failed embed calls do not spawn endless background threads within cooldown."""
    engine = EmbeddingEngine("sentence-transformers/all-MiniLM-L6-v2", load_timeout=1.0, retry_cooldown=10.0)

    init_call_count = 0

    def mock_run_init():
        nonlocal init_call_count
        init_call_count += 1
        engine._init_error = RuntimeError("Simulated network/model failure")
        engine._last_failure_time = time.time()
        engine._init_done.set()

    with mock.patch.object(engine, "_run_init", side_effect=mock_run_init):
        with pytest.raises(RuntimeError, match="Embedding model initialization failed"):
            engine.embed_texts(["hello"])

        assert init_call_count == 1

        for _ in range(9):
            with pytest.raises(RuntimeError, match="Embedding model initialization failed"):
                engine.embed_texts(["hello"])

        assert init_call_count == 1

        engine.reset_init_state()
        with pytest.raises(RuntimeError, match="Embedding model initialization failed"):
            engine.embed_texts(["hello"])

        assert init_call_count == 2


def test_reranker_failed_init_no_thread_leak():
    """Verifies that repeated failed rerank calls do not spawn endless background threads within cooldown."""
    reranker = Reranker("BAAI/bge-reranker-base", load_timeout=1.0, retry_cooldown=10.0)

    init_call_count = 0

    def mock_run_init():
        nonlocal init_call_count
        init_call_count += 1
        reranker._init_error = RuntimeError("Simulated reranker download failure")
        reranker._last_failure_time = time.time()
        reranker._init_done.set()

    with mock.patch.object(reranker, "_run_init", side_effect=mock_run_init):
        with pytest.raises(RuntimeError, match="Reranker model initialization failed"):
            reranker.rerank("query", [{"chunk_id": "c1", "content": "text"}])

        assert init_call_count == 1

        for _ in range(4):
            with pytest.raises(RuntimeError, match="Reranker model initialization failed"):
                reranker.rerank("query", [{"chunk_id": "c1", "content": "text"}])

        assert init_call_count == 1

        reranker.reset_init_state()
        with pytest.raises(RuntimeError, match="Reranker model initialization failed"):
            reranker.rerank("query", [{"chunk_id": "c1", "content": "text"}])

        assert init_call_count == 2


def test_sqlite_vec_store_adaptive_search_candidate_accumulation():
    """Verifies that SqliteVecStore preserves candidates found across multiple adaptive expansion iterations."""
    db = DatabaseManager(":memory:")
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/dev/test_adaptive")
        fid = folder["folder_id"]

        store = SqliteVecStore(conn, dimension=4)
        vectors = []

        for i in range(10):
            ext = ".txt" if i < 5 else ".md"
            f = repo.upsert_file(
                folder_id=fid,
                path=f"C:/dev/test_adaptive/file_{i}{ext}",
                relative_path=f"file_{i}{ext}",
                filename=f"file_{i}{ext}",
                extension=ext,
                size_bytes=100,
                modified_at="2026-09-02T12:00:00Z",
                index_status="INDEXED",
            )
            cid = f"chunk_{i}"
            repo.replace_file_chunks(
                f["file_id"],
                [{
                    "chunk_id": cid,
                    "file_id": f["file_id"],
                    "source_file": f["filename"],
                    "source_path": f["path"],
                    "page": 1,
                    "section": "General",
                    "h1_parent": None,
                    "h2_parent": None,
                    "line_start": 1,
                    "line_end": 5,
                    "char_start": 0,
                    "char_end": 50,
                    "content_hash": f"chash_{i}",
                    "chunk_index": 0,
                    "parser_name": "text",
                    "parser_version": "1.0",
                    "chunker_version": "1.0",
                    "content": f"Content for file {i}",
                    "content_type": "text",
                    "token_count": 10,
                    "metadata": {},
                }]
            )
            emb = [1.0 - (i * 0.08), float(i) * 0.05, 0.0, 0.0]
            norm = (sum(x * x for x in emb)) ** 0.5
            norm_emb = [x / norm for x in emb]
            vectors.append({"chunk_id": cid, "embedding": norm_emb, "file_id": f["file_id"]})

        store.upsert_vectors(vectors)

        q_vec = [1.0, 0.0, 0.0, 0.0]
        results = store.search(q_vec, top_k=3, filters={"extension": ".md"})

        assert len(results) == 3
        result_cids = [r["chunk_id"] for r in results]
        assert result_cids == ["chunk_5", "chunk_6", "chunk_7"]
        for r in results:
            assert r["source_file"].endswith(".md")
            assert r["retrieval_method"] == "dense"
            assert -1.0 <= r["score"] <= 1.0


def test_discovery_version_invalidation_exception_resilience(tmp_path):
    """Verifies that an unexpected exception during version invalidation check is logged and does not crash discovery."""
    db = DatabaseManager(":memory:")
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_path))
        fid = folder["folder_id"]

        test_file = tmp_path / "doc.txt"
        test_file.write_text("sample content", encoding="utf-8")

        scanner = FilesystemScanner(repo)
        res1 = scanner.scan_folder(fid)
        assert res1.new_files == 1

        files = repo.list_files(folder_id=fid)
        f_rec = files[0]
        repo.update_file_status(f_rec["file_id"], "INDEXED")
        with conn:
            conn.execute("UPDATE files SET sha256 = 'valid_sha256' WHERE file_id = ?;", (f_rec["file_id"],))

        with mock.patch(
            "app.intelligence.parsers.registry.default_parser_registry.get_parser_for_file",
            side_effect=RuntimeError("Simulated parser registry exception"),
        ):
            res2 = scanner.scan_folder(fid)
            assert res2.unchanged_files == 1
            assert len(res2.errors) == 0


def test_generation_service_typeerror_signature_handling():
    """Verifies that TypeError from signature mismatch is handled while unrelated internal TypeErrors are propagated."""
    mock_provider = mock.MagicMock(spec=OllamaProvider)
    mock_provider.base_url = "http://127.0.0.1:11434"
    mock_provider.model = "qwen3:4b"

    def legacy_generate(prompt_str, **kwargs):
        if "temperature" in kwargs:
            raise TypeError("generate() got an unexpected keyword argument 'temperature'")
        return OllamaResponse(
            response="Answer with temperature fallback [E1]",
            model="qwen3:4b",
            done=True,
            done_reason="stop",
            prompt_eval_count=50,
            eval_count=20,
        )

    mock_provider.generate.side_effect = legacy_generate
    svc = GroundedGenerationService(provider=mock_provider)

    context_item = ContextItem(
        chunk_id="chk_1",
        file_id="fid_1",
        source_file="doc.txt",
        source_path="C:/dev/doc.txt",
        content="FileMind is a local second brain.",
        estimated_tokens=10,
    )
    context_pkg = BoundedContextPackage(
        status=EvidenceStatus.READY,
        items=[context_item],
        budget=BudgetAccounting(
            total_budget=4096,
            system_reserved=500,
            output_reserved=1000,
            evidence_budget=2596,
            evidence_used=50,
            evidence_remaining=2546,
            candidates_considered=1,
            candidates_included=1,
            candidates_omitted=0,
            omitted_candidates=[],
        ),
    )

    resp = svc.generate_answer("What is FileMind?", context_pkg, GenerationConfig(temperature=0.7))
    assert resp.generation_status == GenerationStatus.READY
    assert "temperature fallback" in resp.answer

    mock_provider.generate.reset_mock()
    mock_provider.generate.side_effect = TypeError("unsupported operand type(s) for +: 'int' and 'str'")
    resp2 = svc.generate_answer("What is FileMind?", context_pkg, GenerationConfig(temperature=0.7))
    assert resp2.generation_status == GenerationStatus.GENERATION_FAILED
    assert "unsupported operand" in resp2.error
    assert mock_provider.generate.call_count == 1
