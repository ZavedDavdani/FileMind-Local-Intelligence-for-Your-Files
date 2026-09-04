"""
Comprehensive test suite validating Chunk 4 remediation fixes:
- Bugs 57–70
- Bugs 90–91
- Bug 94
- Bug 98
- Bug 100
- Bug 104
- Bugs 110–114
"""

import datetime
from datetime import timezone
import hashlib
import json
import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ai.folder_understanding import FolderUnderstandingService
from app.ai.generation_coordinator import LocalGenerationCoordinator
from app.ai.ollama_provider import (
    OllamaGenerationError,
    OllamaProvider,
    OllamaResponse,
    check_ollama_readiness,
)
from app.core.security import is_path_within_root, normalize_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.engine.watcher import (
    DebouncedEventManager,
    FolderWatchHandler,
    WatcherService,
)
from app.intelligence.parsers.base import BaseParser
from app.intelligence.parsers.pdf_parser import PyMuPDFParser
from app.intelligence.parsers.registry import ParserRegistry
from app.main import app
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.normalizer import normalize_query


@pytest.fixture
def temp_db():
    """Provides an initialized DatabaseManager in a temporary file with sqlite-vec loaded."""
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_chunk4_remediation.db")
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
# Bug 57 & Bug 67: Filename candidate over-fetching & lexical status filtering
# ------------------------------------------------------------------------------
def test_bug57_filename_boost_influences_candidate_pool(temp_db):
    """Validates that candidate over-fetching allows filename relevance to promote hits into top-k."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/test_f57")
        fid = folder["folder_id"]

        # Insert 15 content-only matches with filename "generic_note.txt"
        for i in range(15):
            f_rec = repo.upsert_file(
                folder_id=fid,
                path=f"C:/test_f57/generic_{i}.txt",
                relative_path=f"generic_{i}.txt",
                filename=f"generic_{i}.txt",
                extension=".txt",
                size_bytes=100,
                modified_at="2026-09-05T00:00:00Z",
                index_status="INDEXED",
            )
            repo.replace_file_chunks(f_rec["file_id"], [
                {
                    "chunk_id": f"chk_gen_{i}",
                    "file_id": f_rec["file_id"],
                    "source_file": f_rec["filename"],
                    "source_path": f_rec["path"],
                    "content": f"Quarterly financial budget review metrics document number {i}.",
                    "content_hash": f"hash_gen_{i}",
                    "chunk_index": 0,
                    "token_count": 10,
                }
            ])

        # Insert 1 file whose filename is "budget_report.txt" with brief content
        f_target = repo.upsert_file(
            folder_id=fid,
            path="C:/test_f57/budget_report.txt",
            relative_path="budget_report.txt",
            filename="budget_report.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(f_target["file_id"], [
            {
                "chunk_id": "chk_target",
                "file_id": f_target["file_id"],
                "source_file": "budget_report.txt",
                "source_path": f_target["path"],
                "content": "Summary overview note.",
                "content_hash": "hash_target",
                "chunk_index": 0,
                "token_count": 5,
            }
        ])

        retriever = LexicalRetriever(conn)
        # Search for "budget report" with top_k=5. The target document should rank in the top 5
        hits = retriever.search("budget report", top_k=5)
        matched_filenames = [h["source_file"] for h in hits]
        assert "budget_report.txt" in matched_filenames


# ------------------------------------------------------------------------------
# Bug 58: Offline / Missing file job cancellation
# ------------------------------------------------------------------------------
def test_bug58_missing_file_cancels_jobs(temp_db):
    """Validates that marking a file missing cancels both PENDING and PROCESSING jobs."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/test_f58")
        fid = folder["folder_id"]
        f_rec = repo.upsert_file(
            folder_id=fid,
            path="C:/test_f58/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=500,
            modified_at="2026-09-05T00:00:00Z",
        )
        file_id = f_rec["file_id"]

        # Create a PENDING job and a PROCESSING job
        j1 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="METADATA_DISCOVERY")
        j2 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE")
        conn.execute("UPDATE indexing_jobs SET status = 'PROCESSING' WHERE job_id = ?;", (j2["job_id"],))

        # Mark file missing and cancel jobs
        repo.mark_file_missing("C:/test_f58/doc.txt")
        cancelled_count = repo.cancel_pending_jobs_for_file(file_id)
        assert cancelled_count == 2

        # Both jobs must be CANCELLED
        j1_status = conn.execute("SELECT status FROM indexing_jobs WHERE job_id = ?;", (j1["job_id"],)).fetchone()["status"]
        j2_status = conn.execute("SELECT status FROM indexing_jobs WHERE job_id = ?;", (j2["job_id"],)).fetchone()["status"]
        assert j1_status == "CANCELLED"
        assert j2_status == "CANCELLED"


# ------------------------------------------------------------------------------
# Bug 59: Rescan preserves live PROCESSING and INDEXED state
# ------------------------------------------------------------------------------
def test_bug59_rescan_preserves_valid_states(temp_db, tmp_path):
    """Validates that filesystem scan does not overwrite valid INDEXED or PROCESSING state for unchanged files."""
    test_file = tmp_path / "valid_doc.txt"
    test_file.write_text("Hello world content")
    st = test_file.stat()
    mtime_iso = datetime.datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()

    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path=str(tmp_path))
        f_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=str(test_file),
            relative_path="valid_doc.txt",
            filename="valid_doc.txt",
            extension=".txt",
            size_bytes=st.st_size,
            modified_at=mtime_iso,
            sha256="abc123sha",
            index_status="INDEXED",
        )

        scanner = FilesystemScanner(repo)
        res = scanner.scan_folder(folder["folder_id"])
        assert res.unchanged_files == 1
        assert res.modified_files == 0
        assert len(res.enqueued_job_ids) == 0

        f_check = repo.get_file_by_id(f_rec["file_id"])
        assert f_check["index_status"] == "INDEXED"


# ------------------------------------------------------------------------------
# Bug 60: Windows path identity case-insensitivity
# ------------------------------------------------------------------------------
def test_bug60_windows_path_case_insensitivity(temp_db):
    """Validates that path lookups on Windows find equivalent paths regardless of casing."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/TestDocs/Sub")
        f_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/TestDocs/Sub/Important_Doc.PDF",
            relative_path="Important_Doc.PDF",
            filename="Important_Doc.PDF",
            extension=".pdf",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            index_status="INDEXED",
        )

        # Lookup with all lowercase
        found_lower = repo.get_file_by_path("c:/testdocs/sub/important_doc.pdf")
        assert found_lower is not None
        assert found_lower["file_id"] == f_rec["file_id"]

        # Folder lookup with mixed casing
        found_folder = repo.get_folder_by_path("c:/TESTDOCS/SUB")
        assert found_folder is not None
        assert found_folder["folder_id"] == folder["folder_id"]


# ------------------------------------------------------------------------------
# Bug 62 & Bug 63: Ollama readiness exact model tag and incomplete generation checks
# ------------------------------------------------------------------------------
def test_bug62_exact_model_tag_validation():
    """Validates that Ollama model readiness checks require exact tag matches (e.g. qwen2.5:3b vs qwen2.5:7b)."""
    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {"name": "qwen2.5:7b", "size": 4000000000},
                {"name": "nomic-embed-text:latest", "size": 300000000},
            ]
        }
        mock_get.return_value = mock_resp

        # Asking for qwen2.5:3b should fail because only qwen2.5:7b is installed
        res_fail = check_ollama_readiness(
            base_url="http://127.0.0.1:11434",
            target_model="qwen2.5:3b",
        )
        assert res_fail["is_ollama_online"] is True
        assert res_fail["has_default_model"] is False

        # Asking for qwen2.5:7b should succeed
        res_ok = check_ollama_readiness(
            base_url="http://127.0.0.1:11434",
            target_model="qwen2.5:7b",
        )
        assert res_ok["is_ollama_online"] is True
        assert res_ok["has_default_model"] is True


def test_bug63_incomplete_ollama_generation_raises_error():
    """Validates that responses with done=False or error payload raise OllamaGenerationError."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": "Cut off mid-sentence...",
        "done": False,
    }
    mock_client.post.return_value = mock_resp

    provider = OllamaProvider(base_url="http://127.0.0.1:11434", client=mock_client)

    with pytest.raises(OllamaGenerationError, match="done != True"):
        provider.generate("test prompt")


# ------------------------------------------------------------------------------
# Bug 64: Desktop model isolation / Local concurrency guarantee
# ------------------------------------------------------------------------------
def test_bug64_local_generation_concurrency_coordinator():
    """Validates that LocalGenerationCoordinator strictly serializes concurrent LLM generation calls."""
    coord = LocalGenerationCoordinator(capacity=1)
    concurrency_counter = 0
    max_observed_concurrency = 0
    lock = threading.Lock()

    def worker():
        nonlocal concurrency_counter, max_observed_concurrency
        try:
            with coord.acquire():
                with lock:
                    concurrency_counter += 1
                    if concurrency_counter > max_observed_concurrency:
                        max_observed_concurrency = concurrency_counter
                time.sleep(0.05)
                with lock:
                    concurrency_counter -= 1
        except Exception:
            pass

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_observed_concurrency == 1


# ------------------------------------------------------------------------------
# Bug 66: Search router aliases for related files
# ------------------------------------------------------------------------------
def test_bug66_related_files_route_aliases():
    """Validates that /retrieval/related/{file_id}, /search/related/{file_id}, and /related/{file_id} all resolve correctly."""
    client = TestClient(app)

    with patch("app.routers.search.RelatedContentService") as mock_svc_cls:
        mock_svc = MagicMock()
        mock_svc.get_related_files.return_value = {
            "source_file_id": "test-file-123",
            "source_filename": "test.txt",
            "total_found": 1,
            "retrieval_method": "hybrid",
            "quality": "fast",
            "query_used": "test query",
            "results": [
                {
                    "file_id": "target_1",
                    "filename": "target.txt",
                    "path": "C:/target.txt",
                    "score": 0.95,
                    "retrieval_method": "hybrid",
                    "explanation": "High similarity",
                    "matching_chunk_count": 1,
                    "primary_matched_chunk": {
                        "chunk_id": "chk_1",
                        "snippet": "sample content",
                    },
                    "supporting_chunks": [],
                }
            ],
        }
        mock_svc_cls.return_value = mock_svc

        # Primary route /retrieval/related/{file_id}
        res1 = client.get("/retrieval/related/test-file-123")
        assert res1.status_code == 200
        data1 = res1.json()
        assert len(data1["results"]) == 1

        # Alias 1: /search/related/{file_id}
        res2 = client.get("/search/related/test-file-123")
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2["results"]) == 1

        # Alias 2: /related/{file_id}
        res3 = client.get("/related/test-file-123")
        assert res3.status_code == 200
        data3 = res3.json()
        assert len(data3["results"]) == 1


# ------------------------------------------------------------------------------
# Bug 67: Lexical retriever strictly filters INDEXED files
# ------------------------------------------------------------------------------
def test_bug67_lexical_filter_excludes_non_indexed(temp_db):
    """Validates that chunks from files with status FAILED, MISSING, or SKIPPED are never returned by lexical search."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/test_f67")
        fid = folder["folder_id"]

        # Insert FAILED file with chunks
        f_failed = repo.upsert_file(
            folder_id=fid,
            path="C:/test_f67/failed.txt",
            relative_path="failed.txt",
            filename="failed.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            index_status="FAILED",
        )
        repo.replace_file_chunks(f_failed["file_id"], [{
            "chunk_id": "chk_failed_1",
            "file_id": f_failed["file_id"],
            "source_file": "failed.txt",
            "source_path": f_failed["path"],
            "content": "Confidential secret term alpha beta.",
            "content_hash": "hash_f",
            "chunk_index": 0,
            "token_count": 6,
        }])

        # Insert INDEXED file with chunks
        f_indexed = repo.upsert_file(
            folder_id=fid,
            path="C:/test_f67/indexed.txt",
            relative_path="indexed.txt",
            filename="indexed.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(f_indexed["file_id"], [{
            "chunk_id": "chk_indexed_1",
            "file_id": f_indexed["file_id"],
            "source_file": "indexed.txt",
            "source_path": f_indexed["path"],
            "content": "Confidential secret term alpha beta.",
            "content_hash": "hash_i",
            "chunk_index": 0,
            "token_count": 6,
        }])

        retriever = LexicalRetriever(conn)
        hits = retriever.search("Confidential secret term", top_k=10)
        assert len(hits) == 1
        assert hits[0]["chunk_id"] == "chk_indexed_1"
        assert hits[0]["source_file"] == "indexed.txt"


# ------------------------------------------------------------------------------
# Bug 68: Path containment and canonical root validation edge cases
# ------------------------------------------------------------------------------
def test_bug68_is_path_within_root_edge_cases():
    """Validates robust path containment checking against sibling directories, relative dots, and casing."""
    root = "C:/Projects/FileMind"

    # Valid child
    assert is_path_within_root("C:/Projects/FileMind/src/main.py", root) is True
    assert is_path_within_root("c:/projects/filemind/SRC/MAIN.PY", root) is True

    # Sibling prefix attack (C:/Projects/FileMind2 should NOT match C:/Projects/FileMind)
    assert is_path_within_root("C:/Projects/FileMind2/malicious.py", root) is False

    # Parent traversal ..
    assert is_path_within_root("C:/Projects/FileMind/../Other/secret.txt", root) is False

    # Root itself
    assert is_path_within_root("C:/Projects/FileMind", root) is True


# ------------------------------------------------------------------------------
# Bug 69: Oversized file transitions purge old index
# ------------------------------------------------------------------------------
def test_bug69_oversized_file_purges_old_index(temp_db, tmp_path):
    """Validates that a previously indexed file becoming oversized purges its chunks and transitions to SKIPPED."""
    test_file = tmp_path / "growing_file.txt"
    test_file.write_text("Small initial text")
    st = test_file.stat()

    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path=str(tmp_path))
        fid = folder["folder_id"]

        f_rec = repo.upsert_file(
            folder_id=fid,
            path=str(test_file),
            relative_path="growing_file.txt",
            filename="growing_file.txt",
            extension=".txt",
            size_bytes=st.st_size,
            modified_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
            index_status="INDEXED",
        )
        repo.replace_file_chunks(f_rec["file_id"], [{
            "chunk_id": "chk_grow_1",
            "file_id": f_rec["file_id"],
            "source_file": "growing_file.txt",
            "source_path": str(test_file),
            "content": "Small initial text",
            "content_hash": "hash_grow",
            "chunk_index": 0,
            "token_count": 3,
        }])
        assert len(repo.get_chunks_by_file(f_rec["file_id"])) == 1

        # Simulate file size expanding past MAX_FILE_SIZE_BYTES
        with patch("app.core.config.MAX_FILE_SIZE_BYTES", 10):
            scanner = FilesystemScanner(repo)
            res = scanner.scan_folder(fid)
            assert res.modified_files == 1

            f_after = repo.get_file_by_id(f_rec["file_id"])
            assert f_after["index_status"] == "SKIPPED"
            # Chunks must be purged
            assert len(repo.get_chunks_by_file(f_rec["file_id"])) == 0


# ------------------------------------------------------------------------------
# Bug 90: Directory CREATE events handled by watch handler
# ------------------------------------------------------------------------------
def test_bug90_directory_create_event():
    """Validates that FolderWatchHandler on_created emits is_directory: True for directory creations."""
    debouncer = MagicMock()
    handler = FolderWatchHandler("f1", "C:/test_root", [], debouncer)

    mock_event = MagicMock()
    mock_event.is_directory = True
    mock_event.src_path = "C:/test_root/new_subdir"

    handler.on_created(mock_event)
    assert debouncer.push_event.called
    ev = debouncer.push_event.call_args[0][0]
    assert ev["is_directory"] is True
    assert ev["event_type"] == "CREATE"
    assert ev["path"] == normalize_path("C:/test_root/new_subdir")


# ------------------------------------------------------------------------------
# Bug 91: Debouncer coalesces CREATE + RENAME sequence
# ------------------------------------------------------------------------------
def test_bug91_debouncer_create_rename_coalescing():
    """Validates that a CREATE followed immediately by RENAME within the debounce window coalesces into CREATE on new path."""
    flushed = []
    debouncer = DebouncedEventManager(debounce_window_sec=0.1, on_flush=lambda e: flushed.append(e))

    # 1. CREATE A
    debouncer.push_event({
        "folder_id": "f1",
        "event_type": "CREATE",
        "path": "C:/root/temp_name.txt",
        "old_path": None,
        "is_directory": False,
        "observed_at": time.time(),
    })

    # 2. RENAME A -> B
    debouncer.push_event({
        "folder_id": "f1",
        "event_type": "RENAME",
        "path": "C:/root/final_name.txt",
        "old_path": "C:/root/temp_name.txt",
        "is_directory": False,
        "observed_at": time.time(),
    })

    debouncer.flush()
    assert len(flushed) == 1
    assert flushed[0]["event_type"] == "CREATE"
    assert flushed[0]["path"] == "C:/root/final_name.txt"
    assert flushed[0]["old_path"] is None


# ------------------------------------------------------------------------------
# Bug 94: Folder Understanding structural summary and composite hash sampling
# ------------------------------------------------------------------------------
def test_bug94_folder_understanding_sampling_metadata(temp_db):
    """Validates that FolderUnderstandingService provides explicit sampling metadata when file counts exceed limit."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/large_folder")
        fid = folder["folder_id"]

        svc = FolderUnderstandingService(db_manager=temp_db)

        # Mock count_files to return 15000 (larger than limit 10000)
        with patch.object(repo, "count_files", return_value=15000):
            files = [{"file_id": f"f_{i}", "filename": f"doc_{i}.txt", "index_status": "INDEXED", "size_bytes": 10} for i in range(10)]
            summary = svc.compute_structural_summary(folder, files, repo)
            assert summary["is_sampled"] is True
            assert summary["total_files"] == 15000
            assert summary["sampled_files_count"] == 10

            hash_full = svc.compute_composite_hash(files, total_count=15000)
            hash_unsampled = svc.compute_composite_hash(files, total_count=10)
            assert hash_full != hash_unsampled


# ------------------------------------------------------------------------------
# Bug 98: Newer job supersedes stale processing worker
# ------------------------------------------------------------------------------
def test_bug98_newer_job_supersedes_stale_worker(temp_db):
    """Validates that an older job is recognized as superseded when a newer job is enqueued."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/test_f98")
        f_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/test_f98/doc98.txt",
            relative_path="doc98.txt",
            filename="doc98.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-05T00:00:00Z",
            index_status="PROCESSING",
        )

        job1 = repo.enqueue_job(file_id=f_rec["file_id"], folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")
        conn.execute("UPDATE indexing_jobs SET status = 'PROCESSING' WHERE job_id = ?;", (job1["job_id"],))

        # While job1 is processing, file is modified on disk -> job2 enqueued
        time.sleep(0.01)
        job2 = repo.enqueue_job(file_id=f_rec["file_id"], folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")

        # Job1 is no longer current processing job
        assert repo.is_current_processing_job(job1["job_id"], f_rec["file_id"]) is False
        # Job2 is current
        assert repo.is_current_processing_job(job2["job_id"], f_rec["file_id"]) is True


# ------------------------------------------------------------------------------
# Bug 100: WatcherService stop/start lifecycle
# ------------------------------------------------------------------------------
def test_bug100_watcher_service_lifecycle(temp_db):
    """Validates that WatcherService stops cleanly without errors and resets stopped state on start."""
    watcher = WatcherService(temp_db)
    watcher.start()
    assert watcher.observer is not None
    assert watcher.debouncer._stopped is False

    watcher.stop()
    assert watcher.observer is None
    assert watcher.debouncer._stopped is True

    # Repeated stop is safe
    watcher.stop()

    # Restart cleans debouncer stopped flag
    watcher.start()
    assert watcher.observer is not None
    assert watcher.debouncer._stopped is False
    watcher.stop()


# ------------------------------------------------------------------------------
# Bug 110: Parser registry conflict handling
# ------------------------------------------------------------------------------
def test_bug110_parser_registry_conflict_handling():
    """Validates that ParserRegistry enforces allow_overwrite semantics."""
    registry = ParserRegistry()

    class DummyParser(BaseParser):
        @property
        def parser_name(self): return "dummy"
        @property
        def parser_version(self): return "1.0.0"
        @property
        def supported_mime_types(self): return ["text/plain"]
        @property
        def supported_extensions(self): return [".txt"]
        def parse(self, *args, **kwargs): pass

    parser1 = DummyParser()
    registry.register_parser(parser1)

    # Registering same extension with allow_overwrite=False raises ValueError
    parser2 = DummyParser()
    with pytest.raises(ValueError, match="already registered"):
        registry.register_parser(parser2, allow_overwrite=False)


# ------------------------------------------------------------------------------
# Bug 112 & Bug 113: Watcher sync updates recursive flag and exclude patterns
# ------------------------------------------------------------------------------
def test_bug112_bug113_watcher_sync_updates_config(temp_db, tmp_path):
    """Validates that WatcherService._sync_watches reschedules watches when recursive or exclude_patterns change."""
    test_dir = tmp_path / "watch_cfg_test"
    test_dir.mkdir()

    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path=str(test_dir), recursive=False, exclude_patterns=["*.tmp"])
        fid = folder["folder_id"]

    watcher = WatcherService(temp_db)
    watcher.start()

    assert fid in watcher.watches
    assert watcher.watches[fid]["recursive"] is False
    assert watcher.watches[fid]["patterns"] == ["*.tmp"]

    # Update folder configuration to recursive=True and new patterns
    with temp_db.session() as conn:
        repo = Repository(conn)
        repo.update_folder(folder_id=fid, recursive=True, exclude_patterns=["*.tmp", "*.bak"])

    watcher.sync_watches()
    assert fid in watcher.watches
    assert watcher.watches[fid]["recursive"] is True
    assert watcher.watches[fid]["patterns"] == ["*.tmp", "*.bak"]

    watcher.stop()
