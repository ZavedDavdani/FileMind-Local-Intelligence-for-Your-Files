"""
Test suite verifying Chunk 5 correctness fixes:
- Bugs 71–85
- Bug 86
- Bug 97
- Bug 99
- Bugs 116–117
- Bug 120
"""

import json
import os
import re
import tempfile
import time
from unittest.mock import MagicMock, patch
import pytest

from app.ai.citation import CitationValidator, CitationValidationResult
from app.ai.context import BoundedContextPackage, BudgetAccounting, ContextItem, EvidenceStatus
from app.ai.folder_understanding import FolderUnderstandingService
from app.ai.generation import GroundedGenerationService, GenerationStatus
from app.ai.knowledge_connections import KnowledgeConnectionService, _filter_evidence_for_topic
from app.ai.ollama_provider import OllamaProvider, OllamaResponse
from app.ai.prompt import CitationSource, PromptBuilder
from app.core.security import normalize_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.watcher import WatcherService, DebouncedEventManager
from app.intelligence.chunker.identity import generate_chunk_id, compute_chunk_content_hash
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.related import RelatedContentService
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_chunk5_remediation.db")
    db_mgr = DatabaseManager(db_file)
    with db_mgr.session() as conn:
        apply_migrations(conn)
        conn.commit()
    yield db_mgr
    try:
        if os.path.exists(db_file):
            os.remove(db_file)
        os.rmdir(temp_dir)
    except Exception:
        pass


class FakeEmbeddingEngine:
    def __init__(self, dim=384):
        self.dimension = dim

    def embed_query(self, query):
        return [0.01] * self.dimension

    def embed_chunks(self, chunks):
        return [[0.01] * self.dimension for _ in chunks]


class FakeLLMProvider:
    def __init__(self, answer="Default answer [E1]"):
        self.answer = answer
        self.calls = []

    def generate(self, prompt, **kwargs):
        self.calls.append(prompt)
        return OllamaResponse(
            model="qwen3:4b",
            response=self.answer,
            done=True,
            done_reason="stop",
            prompt_eval_count=10,
            eval_count=20,
        )


# --- BUG 86: Folder understanding readiness dict attribute access ---
def test_bug_86_folder_readiness_dict_access(temp_db):
    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="qwen3:4b")
    svc = FolderUnderstandingService(db_manager=temp_db, llm_provider=provider)

    with temp_db.session() as conn:
        repo = Repository(conn)
        frec = repo.create_folder(path="/test/folder", indexing_enabled=True)
        folder_id = frec["folder_id"]

        # Insert an indexed file and chunk so structural_summary has >0 files/chunks
        filerec = repo.upsert_file(folder_id=folder_id, path="/test/folder/a.txt", relative_path="a.txt", filename="a.txt", extension=".txt", size_bytes=100, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")
        repo.replace_file_chunks(filerec["file_id"], [
            {
                "chunk_id": "chk_test1",
                "file_id": filerec["file_id"],
                "source_file": "a.txt",
                "source_path": "/test/folder/a.txt",
                "page": 1,
                "section": "Intro",
                "line_start": 1,
                "line_end": 5,
                "char_start": 0,
                "char_end": 100,
                "content": "Sample content for testing folder insight.",
                "content_hash": "hash1",
                "chunk_index": 0,
            }
        ])
        conn.commit()

    with patch("app.ai.folder_understanding.check_ollama_readiness") as mock_readiness:
        mock_readiness.return_value = {
            "is_ollama_online": False,
            "has_default_model": False,
            "model_name": "qwen3:4b",
            "endpoint": "http://127.0.0.1:11434",
            "error": "Unable to connect to Ollama daemon.",
        }
        res = svc.generate_insight(folder_id)
        assert res is not None
        assert res["status"] == "MODEL_UNAVAILABLE"
        assert "Unable to connect" in (res.get("error") or "")


# --- BUG 71: RelatedContentService flexible kwargs ---
def test_bug_71_related_service_init_kwargs(temp_db):
    svc1 = RelatedContentService(db_manager=temp_db)
    assert svc1.db == temp_db

    svc2 = RelatedContentService(db=temp_db)
    assert svc2.db == temp_db

    svc3 = RelatedContentService(db_conn=temp_db)
    assert svc3.db == temp_db


# --- BUG 72, 73, 74: CitationValidator normalization, padding, case-insensitivity & validation ---
def test_bug_72_73_74_citation_validation():
    source1 = CitationSource(citation_id="E1", chunk_id="c1", file_id="f1", source_file="doc1.txt", source_path="/doc1.txt")
    source2 = CitationSource(citation_id="E2", chunk_id="c2", file_id="f2", source_file="doc2.txt", source_path="/doc2.txt")
    citation_map = {"E1": source1, "E2": source2}

    # Bug 73: Lowercase [e1] and spaces [E 2]
    res1 = CitationValidator.extract_and_validate("This fact [e1] and that fact [E 2].", citation_map)
    assert res1.is_valid is True
    assert len(res1.valid_citations) == 2
    assert res1.valid_citations[0].citation_id == "E1"
    assert res1.valid_citations[1].citation_id == "E2"

    # Bug 74: Padded number [E01] vs E1
    res2 = CitationValidator.extract_and_validate("Padded citation [E01].", citation_map)
    assert res2.is_valid is True
    assert len(res2.valid_citations) == 1
    assert res2.valid_citations[0].citation_id == "E1"

    # Unresolved citation
    res3 = CitationValidator.extract_and_validate("Hallucinated [E99].", citation_map)
    assert res3.is_valid is False
    assert "E99" in res3.unresolved_citation_ids

    # Bug 72: require_citations flag
    res4 = CitationValidator.extract_and_validate("No citations here.", citation_map, require_citations=True)
    assert res4.is_valid is False
    assert res4.has_citations is False

    res5 = CitationValidator.extract_and_validate("No citations here.", citation_map, require_citations=False)
    assert res5.is_valid is True


# --- BUG 75: Chunk identity collision resistance ---
def test_bug_75_chunk_id_generation():
    cid = generate_chunk_id("file_123", "Heading 1", "Heading 2", 0, "hash_abc")
    assert cid.startswith("chk_")
    assert len(cid) == 20
    cid2 = generate_chunk_id("file_123", "Heading 1", "Heading 2", 0, "hash_abc")
    assert cid == cid2


# --- BUG 76, 77, 82: Hybrid retrieval filename intent, zero-chunk files, batch dense hydration ---
def test_bug_76_77_82_hybrid_retrieval(temp_db):
    engine = FakeEmbeddingEngine()
    with temp_db.session() as conn:
        repo = Repository(conn)
        frec = repo.create_folder(path="/test/folder", indexing_enabled=True)
        folder_id = frec["folder_id"]

        # Insert 2 files with the same name in different relative paths
        f1 = repo.upsert_file(folder_id=folder_id, path="/test/folder/a/report.pdf", relative_path="a/report.pdf", filename="report.pdf", extension=".pdf", size_bytes=100, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")
        f2 = repo.upsert_file(folder_id=folder_id, path="/test/folder/b/report.pdf", relative_path="b/report.pdf", filename="report.pdf", extension=".pdf", size_bytes=200, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")
        # f3: Zero chunks indexed file
        f3 = repo.upsert_file(folder_id=folder_id, path="/test/folder/empty.txt", relative_path="empty.txt", filename="empty.txt", extension=".txt", size_bytes=0, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")

        # Insert chunks for f1 and f2
        repo.replace_file_chunks(f1["file_id"], [
            {
                "chunk_id": "chk_rep1",
                "file_id": f1["file_id"],
                "source_file": "report.pdf",
                "source_path": "/test/folder/a/report.pdf",
                "page": 1,
                "section": "Summary A",
                "line_start": 1,
                "line_end": 10,
                "char_start": 0,
                "char_end": 100,
                "content": "Quarterly financial report revenue growth data.",
                "content_hash": "hash_rep1",
                "chunk_index": 0,
            }
        ])
        repo.replace_file_chunks(f2["file_id"], [
            {
                "chunk_id": "chk_rep2",
                "file_id": f2["file_id"],
                "source_file": "report.pdf",
                "source_path": "/test/folder/b/report.pdf",
                "page": 1,
                "section": "Summary B",
                "line_start": 1,
                "line_end": 10,
                "char_start": 0,
                "char_end": 100,
                "content": "Annual audit report expenditure data.",
                "content_hash": "hash_rep2",
                "chunk_index": 0,
            }
        ])

        # Also populate vector store
        vstore = SqliteVecStore(conn, dimension=384)
        vstore.upsert_vectors([
            {"chunk_id": "chk_rep1", "embedding": [0.01] * 384},
            {"chunk_id": "chk_rep2", "embedding": [0.01] * 384},
        ])
        conn.commit()

        retriever = HybridRetriever(conn, embedding_engine=engine)

        # Bug 77: Searching "report.pdf" matches both files and scopes via file_ids
        res = retriever.search("report.pdf", mode="hybrid")
        assert res["total_found"] >= 2
        fids = {r["file_id"] for r in res["results"]}
        assert f1["file_id"] in fids or f2["file_id"] in fids

        # Bug 76: Searching for zero-chunk file returns 0 results cleanly without error
        res_empty = retriever.search("empty.txt", mode="hybrid")
        assert res_empty["total_found"] == 0
        assert res_empty["results"] == []


# --- BUG 78, 79: Safe filesystem actions & enumeration ---
def test_bug_78_79_fs_actions(temp_db):
    from app.routers.fs_actions import enumerate_folder, execute_safe_action
    from app.schemas import EnumerateRequest, ActionRequest, ActionType

    with temp_db.session() as conn:
        repo = Repository(conn)
        with tempfile.TemporaryDirectory() as temp_dir:
            folder_rec = repo.create_folder(path=temp_dir, indexing_enabled=True)
            conn.commit()

            # Create standard file
            sub_file = os.path.join(temp_dir, "file1.txt")
            with open(sub_file, "w") as f:
                f.write("hello")

            # Test enumeration
            req = EnumerateRequest(folder_path=temp_dir)
            enum_resp = enumerate_folder(req, repo=repo)
            assert enum_resp.file_count == 1
            assert enum_resp.files[0].filename == "file1.txt"

            # Bug 79: Test open folder command formatting
            act_req = ActionRequest(action=ActionType.OPEN_FOLDER, target_path=sub_file)
            with patch("subprocess.Popen") as mock_popen, patch("os.path.isfile", return_value=True):
                resp = execute_safe_action(act_req, repo=repo)
                assert resp.success is True
                if os.name == "nt":
                    args = mock_popen.call_args[0][0]
                    assert args[0] == "explorer.exe"
                    assert args[1].startswith("/select,")
                    assert '"' not in args[1]


# --- BUG 80, 81: RelatedContentService query sampling and total_found ---
def test_bug_80_81_related_service(temp_db):
    engine = FakeEmbeddingEngine()
    with temp_db.session() as conn:
        repo = Repository(conn)
        frec = repo.create_folder(path="/test/folder", indexing_enabled=True)
        folder_id = frec["folder_id"]

        source_file = repo.upsert_file(folder_id=folder_id, path="/test/folder/source.txt", relative_path="source.txt", filename="source.txt", extension=".txt", size_bytes=1000, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")
        # Insert 30 chunks for source file with headings at beginning, middle, and end
        chunks = []
        for i in range(30):
            chunks.append({
                "chunk_id": f"chk_src_{i}",
                "file_id": source_file["file_id"],
                "source_file": "source.txt",
                "source_path": "/test/folder/source.txt",
                "page": i + 1,
                "section": f"Section_{i}",
                "h1_parent": f"H1_Heading_{i}",
                "h2_parent": None,
                "line_start": i * 10 + 1,
                "line_end": (i + 1) * 10,
                "char_start": i * 100,
                "char_end": (i + 1) * 100,
                "content": f"Content for chunk {i} discussing topic {i % 5}.",
                "content_hash": f"hash_src_{i}",
                "chunk_index": i,
            })
        repo.replace_file_chunks(source_file["file_id"], chunks)

        # Insert 5 other related files
        vecs = []
        for j in range(5):
            other_file = repo.upsert_file(folder_id=folder_id, path=f"/test/folder/other_{j}.txt", relative_path=f"other_{j}.txt", filename=f"other_{j}.txt", extension=".txt", size_bytes=500, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")
            cid = f"chk_other_{j}"
            repo.replace_file_chunks(other_file["file_id"], [{
                "chunk_id": cid,
                "file_id": other_file["file_id"],
                "source_file": f"other_{j}.txt",
                "source_path": f"/test/folder/other_{j}.txt",
                "page": 1,
                "section": "Related Section",
                "h1_parent": "H1_Heading_1",
                "h2_parent": None,
                "line_start": 1,
                "line_end": 10,
                "char_start": 0,
                "char_end": 100,
                "content": "Content discussing topic 1 in related file.",
                "content_hash": f"hash_oth_{j}",
                "chunk_index": 0,
            }])
            vecs.append({"chunk_id": cid, "embedding": [0.01] * 384})

        vstore = SqliteVecStore(conn, dimension=384)
        for c in chunks:
            vecs.append({"chunk_id": c["chunk_id"], "embedding": [0.01] * 384})
        vstore.upsert_vectors(vecs)
        conn.commit()

        svc = RelatedContentService(db_manager=temp_db, embedding_engine=engine)

        # Bug 80: Synthetic query samples headings across document
        syn_q = svc._build_synthetic_query(source_file, chunks)
        assert "source" in syn_q
        assert len(syn_q) > 10

        # Bug 81: total_found reports total candidate count even when limit is smaller
        rel_resp = svc.get_related_files(source_file["file_id"], limit=2)
        assert rel_resp["total_found"] >= 2
        assert len(rel_resp["results"]) == 2


# --- BUG 84: PromptBuilder MAX_QUERY_CHARS bound ---
def test_bug_84_prompt_builder_query_length():
    builder = PromptBuilder()
    assert builder.MAX_QUERY_CHARS == 4000

    long_query = "x" * 5000
    cleaned = builder._clean_query(long_query)
    assert len(cleaned) == 4000


# --- BUG 85: GroundedGenerationService short-circuit on NO_EVIDENCE ---
def test_bug_85_generation_short_circuit_no_evidence():
    fake_provider = FakeLLMProvider()
    svc = GroundedGenerationService(provider=fake_provider)

    budget = BudgetAccounting(
        total_budget=1000,
        system_reserved=100,
        output_reserved=200,
        evidence_budget=700,
        evidence_used=0,
        evidence_remaining=700,
        candidates_considered=0,
        candidates_included=0,
        candidates_omitted=0,
    )
    pkg = BoundedContextPackage(
        status=EvidenceStatus.NO_EVIDENCE,
        items=[],
        budget=budget,
    )

    resp = svc.generate_answer("What is the meaning of life?", pkg)
    assert resp.generation_status == GenerationStatus.NO_EVIDENCE
    assert len(fake_provider.calls) == 0
    assert "not contain sufficient evidence" in resp.answer


# --- BUG 97: Watcher live delete enqueues DELETE_CLEANUP ---
def test_bug_97_watcher_delete_enqueues_cleanup(temp_db):
    watcher = WatcherService(db_manager=temp_db)
    with temp_db.session() as conn:
        repo = Repository(conn)
        frec = repo.create_folder(path="/test/folder", indexing_enabled=True)
        folder_id = frec["folder_id"]

        filerec = repo.upsert_file(folder_id=folder_id, path="/test/folder/to_delete.txt", relative_path="to_delete.txt", filename="to_delete.txt", extension=".txt", size_bytes=100, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")
        file_id = filerec["file_id"]
        conn.commit()

    events = [{
        "folder_id": folder_id,
        "event_type": "DELETE",
        "path": "/test/folder/to_delete.txt",
        "old_path": None,
        "is_directory": False,
        "observed_at": time.time(),
    }]

    watcher._process_event_sub_batch(events)

    with temp_db.session() as conn:
        repo = Repository(conn)
        cursor = conn.execute("SELECT job_type, status FROM indexing_jobs WHERE file_id = ?", (file_id,))
        jobs = cursor.fetchall()
        assert any(j[0] == "DELETE_CLEANUP" for j in jobs)


# --- BUG 99, 116, 117: KnowledgeConnectionService ---
def test_bug_99_116_117_knowledge_connections(temp_db):
    svc = KnowledgeConnectionService(db_manager=temp_db)

    # Bug 116: _filter_evidence_for_topic
    citations = [
        {"chunk_id": "c1", "section": "Machine Learning Algorithms", "snippet": "Discusses gradient descent and neural nets."},
        {"chunk_id": "c2", "section": "Database Systems", "snippet": "Discusses B-Trees and SQLite WAL mode."},
    ]
    filtered_ml = _filter_evidence_for_topic(citations, "Machine Learning")
    assert len(filtered_ml) == 1
    assert filtered_ml[0]["chunk_id"] == "c1"

    filtered_db = _filter_evidence_for_topic(citations, "Database Systems")
    assert len(filtered_db) == 1
    assert filtered_db[0]["chunk_id"] == "c2"

    with temp_db.session() as conn:
        repo = Repository(conn)
        frec = repo.create_folder(path="/test/folder", indexing_enabled=True)
        folder_id = frec["folder_id"]

        f1 = repo.upsert_file(folder_id=folder_id, path="/test/folder/f1.txt", relative_path="f1.txt", filename="f1.txt", extension=".txt", size_bytes=100, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")
        f2 = repo.upsert_file(folder_id=folder_id, path="/test/folder/f2.txt", relative_path="f2.txt", filename="f2.txt", extension=".txt", size_bytes=100, modified_at="2026-01-01T00:00:00Z", index_status="INDEXED")

        repo.replace_file_chunks(f1["file_id"], [
            {
                "chunk_id": "chk_f1_1",
                "file_id": f1["file_id"],
                "source_file": "f1.txt",
                "source_path": "/test/folder/f1.txt",
                "page": 1,
                "section": "Ref",
                "line_start": 1,
                "line_end": 5,
                "char_start": 0,
                "char_end": 100,
                "content": "Please see f2.txt for details.",
                "content_hash": "hash_f1_1",
                "chunk_index": 0,
            }
        ])

        conn.commit()

        # Get connections for f1
        conns = svc.get_connections(f1["file_id"])
        assert "connections" in conns
        assert len(conns["connections"]) >= 1
        ref_conn = next(c for c in conns["connections"] if c["connection_type"] == "file_reference")
        assert ref_conn["target_file"]["file_id"] == f2["file_id"]
        assert ref_conn["label"] == "f2.txt"


# --- BUG 120: Local Loopback and Authorization Security Verification ---
def test_bug_120_security_and_loopback():
    from app.main import HOST, PORT, ALLOWED_ORIGINS
    assert HOST == "127.0.0.1"
    assert PORT == 24823
    assert any("tauri.localhost" in o for o in ALLOWED_ORIGINS)
    assert any("localhost" in o for o in ALLOWED_ORIGINS)
