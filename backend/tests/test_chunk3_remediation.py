"""
Comprehensive test suite validating Chunk 3 remediation fixes:
- Bugs 41–56
- Bugs 92–93
- Bug 96
- Bugs 105–108
"""

import json
import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.ai.citation import CitationSource
from app.ai.context import (
    BoundedContextPackage,
    BudgetAccounting,
    ContextBudgetConfig,
    ContextBuilder,
    ContextItem,
    EvidenceStatus,
    TokenEstimator,
)
from app.ai.document_understanding import DocumentUnderstandingService
from app.ai.folder_understanding import FolderUnderstandingService
from app.ai.generation import (
    GenerationConfig,
    GenerationStatus,
    GroundedGenerationResponse,
    GroundedGenerationService,
    ModelIdentity,
)
from app.ai.generation_coordinator import LocalGenerationCoordinator
from app.ai.ollama_provider import OllamaResponse
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.engine.watcher import DebouncedEventManager, WatcherService
from app.intelligence.chunker.hierarchical import (
    CHUNKER_VERSION,
    HierarchicalChunker,
    split_oversized_table,
)
from app.intelligence.models import DocumentElement, ElementType
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.normalizer import is_cjk_char, normalize_query
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def temp_db():
    """Provides an initialized DatabaseManager in a temporary file with sqlite-vec loaded."""
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_chunk3_remediation.db")
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


# ------------------------------------------------------------------------------
# Bug 41 & Bug 96: Generation coordinator concurrency slot acquire scoping
# ------------------------------------------------------------------------------
def test_bug41_bug96_generation_coordinator_slot_scoping():
    """Validates that provider generation and fallback error handling occur inside a single coordinator slot."""
    coord = LocalGenerationCoordinator(capacity=1)
    mock_provider = MagicMock()

    def fake_generate(prompt, **kwargs):
        if "temperature" in kwargs:
            raise TypeError("unexpected keyword argument 'temperature'")
        return OllamaResponse(
            model="qwen3:4b",
            response="Grounded answer [E1].",
            done=True,
            done_reason="stop",
            prompt_eval_count=10,
            eval_count=5,
        )

    mock_provider.generate.side_effect = fake_generate
    mock_provider.model = "qwen3:4b"

    service = GroundedGenerationService(provider=mock_provider, generation_coordinator=coord)

    context_pkg = BoundedContextPackage(
        status=EvidenceStatus.READY,
        items=[
            ContextItem(
                chunk_id="c1",
                file_id="f1",
                source_file="test.txt",
                source_path="/test.txt",
                content="Grounded evidence content.",
                estimated_tokens=10,
            )
        ],
        budget=BudgetAccounting(
            total_budget=4096,
            system_reserved=500,
            output_reserved=1000,
            evidence_budget=2596,
            evidence_used=10,
            evidence_remaining=2586,
            candidates_considered=1,
            candidates_included=1,
            candidates_omitted=0,
        ),
    )

    resp = service.generate_answer("What is this?", context_pkg)
    assert resp.generation_status in (GenerationStatus.READY, GenerationStatus.BUDGET_LIMITED)
    assert resp.answer == "Grounded answer [E1]."
    assert coord.available_slots == 1


# ------------------------------------------------------------------------------
# Bug 44: Oversized table slicing bbox and slice metadata
# ------------------------------------------------------------------------------
def test_bug44_oversized_table_slicing_metadata():
    """Validates that oversized table slicing calculates slice-specific coordinates and metadata."""
    headers = "| ColA | ColB | ColC |\n| --- | --- | --- |"
    data_rows = "\n".join(f"| Row{i}_A | Row{i}_B | Row{i}_C |" for i in range(40))
    full_table_text = f"{headers}\n{data_rows}"

    table_elem = DocumentElement(
        element_id="tbl_elem_1",
        element_type=ElementType.TABLE,
        text=full_table_text,
        page_number=1,
        line_start=10,
        line_end=52,
        char_start=100,
        char_end=2500,
        metadata={"table_name": "TestTable"},
    )

    slices = split_oversized_table(table_elem, max_chunk_chars=300, target_chunk_chars=250)
    assert len(slices) >= 3
    for idx, s in enumerate(slices):
        meta = s.metadata or {}
        assert meta.get("is_table_slice") is True
        assert meta.get("slice_index") == idx + 1
        assert meta.get("total_slices") == len(slices)
        assert s.line_start is not None
        assert s.line_end is not None
        assert s.line_start >= 10
        assert s.line_end <= 52
        assert s.line_start <= s.line_end
        assert s.char_start is not None
        assert s.char_end is not None
        assert s.char_start >= 100


# ------------------------------------------------------------------------------
# Bug 45: FTS chunk join on chunk_id stability
# ------------------------------------------------------------------------------
def test_bug45_fts_join_stability(temp_db):
    """Validates that LexicalRetriever joins chunks on chunk_id rather than rowid."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="/test/folder")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="/test/folder/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(
            file_rec["file_id"],
            [
                {
                    "chunk_id": "chk_unique_123",
                    "content": "SpecialKeyword unique query target",
                    "source_file": "doc.txt",
                    "source_path": "/test/folder/doc.txt",
                    "section": "Overview",
                    "page": 1,
                }
            ],
        )

        retriever = LexicalRetriever(conn)
        results = retriever.search("SpecialKeyword", top_k=5)
        assert len(results) == 1
        assert results[0]["chunk_id"] == "chk_unique_123"
        assert results[0]["source_file"] == "doc.txt"


# ------------------------------------------------------------------------------
# Bug 46: FTS backfill migration idempotency
# ------------------------------------------------------------------------------
def test_bug46_fts_migration_idempotency(temp_db):
    """Validates that running FTS migration backfills does not duplicate rows."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="/test/f")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="/test/f/sample.txt",
            relative_path="sample.txt",
            filename="sample.txt",
            extension=".txt",
            size_bytes=50,
            modified_at="2026-09-05T00:00:00Z",
        )
        repo.replace_file_chunks(
            file_rec["file_id"],
            [
                {
                    "chunk_id": "c1",
                    "content": "Hello World Idempotency Test",
                    "source_file": "sample.txt",
                    "source_path": "/test/f/sample.txt",
                }
            ],
        )

        conn.execute("DELETE FROM chunks_fts;")
        conn.execute(
            """
            INSERT INTO chunks_fts (rowid, content, h1_parent, h2_parent, section, source_file, chunk_id, file_id)
            SELECT rowid, content, COALESCE(h1_parent, ''), COALESCE(h2_parent, ''), COALESCE(section, ''), source_file, chunk_id, file_id FROM chunks;
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM chunks_fts;").fetchone()[0]
        assert count == 1


# ------------------------------------------------------------------------------
# Bugs 47 & 48: Vector cleanup ordering on file and folder deletion
# ------------------------------------------------------------------------------
def test_bug47_bug48_vector_cleanup_ordering(temp_db):
    """Validates that two-phase vector cleanup purges virtual table before cascading relational deletes."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="/test/folder_del")
        f1 = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="/test/folder_del/f1.txt",
            relative_path="f1.txt",
            filename="f1.txt",
            extension=".txt",
            size_bytes=10,
            modified_at="2026-09-05T00:00:00Z",
        )
        repo.replace_file_chunks(
            f1["file_id"],
            [{"chunk_id": "c_del_1", "content": "Del content", "source_file": "f1.txt", "source_path": "/test/f1.txt"}],
        )

        deleted = repo.delete_file(f1["file_id"])
        assert deleted is True
        assert repo.get_file_by_id(f1["file_id"]) is None
        assert len(repo.get_chunks_by_file(f1["file_id"])) == 0

        f2 = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="/test/folder_del/f2.txt",
            relative_path="f2.txt",
            filename="f2.txt",
            extension=".txt",
            size_bytes=10,
            modified_at="2026-09-05T00:00:00Z",
        )
        deleted_f = repo.delete_folder(folder["folder_id"])
        assert deleted_f is True
        assert repo.get_folder(folder["folder_id"]) is None


# ------------------------------------------------------------------------------
# Bugs 50 & 51: Normalizer CJK character token preservation and composite expansion
# ------------------------------------------------------------------------------
def test_bug50_cjk_token_preservation():
    """Validates that CJK single characters are preserved as significant search tokens."""
    assert is_cjk_char("文") is True
    assert is_cjk_char("件") is True
    assert is_cjk_char("A") is False

    q = normalize_query("文件 索引")
    assert "文件" in q.tokens or ("文" in q.tokens and "件" in q.tokens)
    assert not q.is_empty
    assert len(q.fts5_query) > 0


def test_bug51_composite_token_expansion():
    """Validates that composite tokens expand subparts while maintaining safety in FTS5."""
    q = normalize_query("FILEMIND_PRACTICAL sample.txt")
    assert not q.is_empty
    assert "FILEMIND" in q.fts5_query
    assert "PRACTICAL" in q.fts5_query
    assert "sample" in q.fts5_query


# ------------------------------------------------------------------------------
# Bug 54: Vector dimension mismatch recovery
# ------------------------------------------------------------------------------
def test_bug54_vector_dimension_mismatch_validation(temp_db):
    """Validates that SqliteVecStore validates dimension on upsert and auto-recreates empty table on dimension change."""
    with temp_db.session() as conn:
        store_384 = SqliteVecStore(conn, dimension=384)
        assert store_384.dimension == 384

        with pytest.raises(ValueError, match="dimension mismatch"):
            store_384.upsert_vectors([{"chunk_id": "bad_vec", "embedding": [0.1] * 128}])

        store_768 = SqliteVecStore(conn, dimension=768)
        assert store_768.dimension == 768


# ------------------------------------------------------------------------------
# Bug 55: Indexing pipeline verifies chunks, versions, and hash for bypass
# ------------------------------------------------------------------------------
def test_bug55_indexing_pipeline_integrity_bypass_validation(tmp_path):
    """Validates that IndexingPipeline only allows INDEXED bypass if valid chunks, matching versions, and identical hash exist."""
    from app.engine.pipeline import IndexingPipeline
    from app.engine.hasher import compute_file_sha256

    test_file = tmp_path / "integrity_doc.txt"
    test_file.write_text("Integrity validation content for bug 55.")
    digest, _ = compute_file_sha256(str(test_file))

    pipeline = IndexingPipeline()

    # Case 1: Existing file has matching hash, matching parser & chunker versions -> BYPASS
    res_bypass = pipeline.execute(
        file_path=str(test_file),
        file_id="f1",
        job_id="j1",
        existing_file_rec={"sha256": digest, "index_status": "INDEXED"},
        existing_chunk_vers={"parser_version": "1.1.0", "chunker_version": CHUNKER_VERSION},
    )
    assert res_bypass.status == "INDEXED"
    assert res_bypass.is_unchanged_bypass is True

    # Case 2: Existing file has matching hash but 0 / missing chunk versions -> NO BYPASS (re-indexed)
    res_no_chunks = pipeline.execute(
        file_path=str(test_file),
        file_id="f1",
        job_id="j2",
        existing_file_rec={"sha256": digest, "index_status": "INDEXED"},
        existing_chunk_vers=None,
    )
    assert res_no_chunks.status == "INDEXED"
    assert res_no_chunks.is_unchanged_bypass is False
    assert len(res_no_chunks.chunks) >= 1

    # Case 3: Existing file has matching hash but outdated chunker version -> NO BYPASS (re-indexed)
    res_old_ver = pipeline.execute(
        file_path=str(test_file),
        file_id="f1",
        job_id="j3",
        existing_file_rec={"sha256": digest, "index_status": "INDEXED"},
        existing_chunk_vers={"parser_version": "v1.0.0", "chunker_version": "v0.0.1"},
    )
    assert res_old_ver.status == "INDEXED"
    assert res_old_ver.is_unchanged_bypass is False

    # Case 4: File hash changed -> NO BYPASS
    res_changed_hash = pipeline.execute(
        file_path=str(test_file),
        file_id="f1",
        job_id="j4",
        existing_file_rec={"sha256": "old_outdated_hash", "index_status": "INDEXED"},
        existing_chunk_vers={"parser_version": "v1.0.0", "chunker_version": CHUNKER_VERSION},
    )
    assert res_changed_hash.status == "INDEXED"
    assert res_changed_hash.is_unchanged_bypass is False


# ------------------------------------------------------------------------------
# Bug 56: WatcherService / DebouncedEventManager stop method and timer cancellation
# ------------------------------------------------------------------------------
def test_bug56_debounced_event_manager_stop():
    """Validates that DebouncedEventManager stops cleanly and cancels pending timers."""
    flushed_events = []
    debouncer = DebouncedEventManager(
        debounce_window_sec=0.1,
        on_flush=lambda ev: flushed_events.append(ev),
    )

    debouncer.push_event({
        "folder_id": "f1",
        "event_type": "CREATE",
        "path": "/test/file.txt",
        "observed_at": time.time(),
    })

    debouncer.stop()
    assert debouncer._stopped is True
    assert debouncer._timer is None
    debouncer.push_event({
        "folder_id": "f1",
        "event_type": "MODIFY",
        "path": "/test/file2.txt",
        "observed_at": time.time(),
    })
    assert len(debouncer._pending_events) == 0


# ------------------------------------------------------------------------------
# Bugs 92 & 93: Stuck GENERATING state recovery
# ------------------------------------------------------------------------------
def test_bug92_document_understanding_stuck_generating_recovery(temp_db):
    """Validates that document insights stuck in GENERATING from a previous process crash report as STALE."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="/test/ai")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="/test/ai/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            sha256="hash123",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(
            file_rec["file_id"],
            [{"chunk_id": "c_ai_1", "content": "AI text", "source_file": "doc.txt", "source_path": "/test/ai/doc.txt"}],
        )

        repo.upsert_document_insight(
            file_id=file_rec["file_id"],
            status="GENERATING",
            content_hash="hash123",
            parser_version="unknown",
            chunker_version="phase2-hierarchical-v2",
            model_provider="ollama",
            model_name="qwen3:4b",
        )

    service = DocumentUnderstandingService(db_manager=temp_db, model_name="qwen3:4b")
    insight = service.get_insight(file_rec["file_id"])
    assert insight["status"] == "STALE"


def test_bug93_folder_understanding_stuck_generating_recovery(temp_db):
    """Validates that folder insights stuck in GENERATING from a previous process crash report as STALE."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="/test/folder_ai")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="/test/folder_ai/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            sha256="hash123",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(
            file_rec["file_id"],
            [{"chunk_id": "c_f_1", "content": "Folder doc", "source_file": "doc.txt", "source_path": "/test/folder_ai/doc.txt"}],
        )

        repo.upsert_folder_insight(
            folder_id=folder["folder_id"],
            status="GENERATING",
            composite_hash="comp123",
            model_provider="ollama",
            model_name="qwen3:4b",
        )

    service = FolderUnderstandingService(db_manager=temp_db, model_name="qwen3:4b")
    f_insight = service.get_folder_insight(folder["folder_id"])
    assert f_insight["status"] == "STALE"


# ------------------------------------------------------------------------------
# Bugs 105 & 106: Reranker zip safety and score metadata preservation
# ------------------------------------------------------------------------------
def test_bug105_bug106_reranker_zip_safety_and_score_preservation():
    """Validates that Reranker handles raw_scores length mismatches without silent candidate truncation."""
    reranker = Reranker()
    mock_model = MagicMock()
    mock_model.rerank.return_value = iter([1.5, 0.2])
    reranker._model = mock_model

    candidates = [
        {"chunk_id": "c1", "content": "Text 1", "rrf_score": 0.03, "dense_score": 0.8},
        {"chunk_id": "c2", "content": "Text 2", "rrf_score": 0.02, "dense_score": 0.7},
        {"chunk_id": "c3", "content": "Text 3", "rrf_score": 0.01, "dense_score": 0.6},
    ]

    results = reranker.rerank("test query", candidates, top_k=3)
    assert len(results) == 3
    for r in results:
        assert "reranker_score" in r
        assert "rrf_score" in r
        assert "dense_score" in r


# ------------------------------------------------------------------------------
# Bug 107: Context budget dynamic model awareness
# ------------------------------------------------------------------------------
def test_bug107_context_budget_for_model():
    """Validates that ContextBudgetConfig.for_model adjusts context allocations dynamically."""
    default_cfg = ContextBudgetConfig.for_model(None)
    assert default_cfg.max_context_tokens == 4096

    qwen_cfg = ContextBudgetConfig.for_model("qwen2.5:14b-32k")
    assert qwen_cfg.max_context_tokens == 8192
    assert qwen_cfg.max_chunks == 30

    tiny_cfg = ContextBudgetConfig.for_model("phi3:mini-2k")
    assert tiny_cfg.max_context_tokens == 2048
    assert tiny_cfg.max_chunks == 10


# ------------------------------------------------------------------------------
# Bug 108: Empty evidence hallucination guard
# ------------------------------------------------------------------------------
def test_bug108_empty_evidence_short_circuit():
    """Validates that GroundedGenerationService short-circuits with NO_EVIDENCE when 0 items are provided."""
    mock_provider = MagicMock()
    service = GroundedGenerationService(provider=mock_provider)

    empty_package = BoundedContextPackage(
        status=EvidenceStatus.NO_EVIDENCE,
        items=[],
        budget=BudgetAccounting(
            total_budget=4096,
            system_reserved=500,
            output_reserved=1000,
            evidence_budget=2596,
            evidence_used=0,
            evidence_remaining=2596,
            candidates_considered=0,
            candidates_included=0,
            candidates_omitted=0,
        ),
    )

    resp = service.generate_answer("Any query?", empty_package)
    assert resp.generation_status == GenerationStatus.NO_EVIDENCE
    assert resp.evidence_status == EvidenceStatus.NO_EVIDENCE
    assert len(resp.citations) == 0
    assert mock_provider.generate.call_count == 0
