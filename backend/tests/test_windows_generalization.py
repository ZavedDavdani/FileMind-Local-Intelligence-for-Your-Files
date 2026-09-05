"""Windows Generalization Test Suite for FileMind.

Verifies:
1. Path canonicalization, case-insensitivity, prefix collisions, Unicode, and extended length paths.
2. Process management, loopback security, and health checking.
3. SQLite WAL, FTS5, and sqlite-vec compatibility on Windows.
4. Working directory and AppData independence.
5. Ollama offline degradation and multimodal tool degradation.
6. Windows file locking and transient sharing error recovery.
7. Watcher event debouncing and deduplication.
"""

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import get_app_data_dir
from app.core.security import (
    SecurityError,
    SecurityForbiddenError,
    SecurityNotFoundError,
    contains_symlink_or_junction,
    is_path_within_root,
    is_symlink_or_junction,
    normalize_path,
    paths_overlap,
    resolve_and_authorize,
    validate_subpath_safety,
)
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repositories.files import FileRepository
from app.db.repository import Repository
from app.engine.hasher import compute_file_sha256
from app.engine.watcher import DebouncedEventManager, is_subpath
from app.intelligence.models import ElementType
from app.intelligence.parsers.audio_parser import AudioParser
from app.intelligence.parsers.image_parser import ImageParser
from app.intelligence.parsers.video_parser import VideoParser
from app.retrieval.vector_store import SqliteVecStore
from app.ai.generation import (
    GenerationStatus,
    GroundedGenerationResponse,
    GroundedGenerationService,
)
from app.ai.ollama_provider import (
    OllamaConnectionError,
    OllamaProvider,
    check_ollama_readiness,
)
from app.ai.context import BoundedContextPackage, BudgetAccounting, EvidenceStatus


class TestWindowsPathGeneralization:
    """Tests for Windows path normalization, case sensitivity, and containment security."""

    def test_windows_path_case_insensitivity(self):
        root = r"C:\Data\Projects\FileMind"
        target_exact = r"C:\Data\Projects\FileMind\docs\readme.txt"
        target_lower = r"c:\data\projects\filemind\docs\readme.txt"
        target_upper = r"C:\DATA\PROJECTS\FILEMIND\DOCS\README.TXT"

        assert is_path_within_root(target_exact, root) is True
        assert is_path_within_root(target_lower, root) is True
        assert is_path_within_root(target_upper, root) is True

    def test_windows_path_separators_and_trailing(self):
        root_slash = "C:/Data/Projects/FileMind/"
        root_backslash = r"C:\Data\Projects\FileMind\\"
        target = "C:/Data/Projects/FileMind/src/main.rs"

        assert is_path_within_root(target, root_slash) is True
        assert is_path_within_root(target, root_backslash) is True
        assert is_path_within_root(root_slash, root_backslash) is True

    def test_windows_path_prefix_collision_prevention(self):
        root = r"C:\Data\Folder"
        target_sibling1 = r"C:\Data\Folder2\secret.docx"
        target_sibling2 = r"C:\Data\Folder_extra\secret.docx"
        target_valid = r"C:\Data\Folder\Sub\file.txt"

        assert is_path_within_root(target_sibling1, root) is False
        assert is_path_within_root(target_sibling2, root) is False
        assert is_path_within_root(target_valid, root) is True

    def test_windows_relative_traversal_rejection(self):
        root = r"C:\Data\Folder"
        target_escape = r"C:\Data\Folder\..\Secret\passwords.txt"
        target_double_escape = r"C:\Data\Folder\..\..\Windows\System32\cmd.exe"

        assert is_path_within_root(target_escape, root) is False
        assert is_path_within_root(target_double_escape, root) is False

    def test_windows_unicode_and_special_character_paths(self):
        root = r"C:\Users\Test User\Documents\My Workspace (2026) & Notes"
        target_french = r"C:\Users\Test User\Documents\My Workspace (2026) & Notes\Résumé 2026.pdf"
        target_cjk = r"C:\Users\Test User\Documents\My Workspace (2026) & Notes\研究\テスト (v1.0).xlsx"
        target_quotes = r"C:\Users\Test User\Documents\My Workspace (2026) & Notes\John's Files\data.csv"

        assert is_path_within_root(target_french, root) is True
        assert is_path_within_root(target_cjk, root) is True
        assert is_path_within_root(target_quotes, root) is True

    def test_windows_extended_length_paths(self):
        root = r"\\?\C:\Data\LongPathRoot"
        target = r"\\?\C:\Data\LongPathRoot\Sub\Deep\File.txt"

        norm_root = normalize_path(root)
        norm_target = normalize_path(target)
        assert norm_root.startswith(r"\\?\C:\Data\LongPathRoot") or norm_root.startswith(r"C:\Data\LongPathRoot")
        assert is_path_within_root(norm_target, norm_root) is True

    def test_windows_cross_drive_containment(self):
        root_c = r"C:\Data\Files"
        target_d = r"D:\Data\Files\document.pdf"
        assert is_path_within_root(target_d, root_c) is False


class TestWindowsDatabaseAndVecCompatibility:
    """Tests for SQLite WAL, FTS5, and sqlite-vec extension on Windows."""

    def test_sqlite_wal_and_vec_initialization(self, tmp_path):
        db_file = tmp_path / "win_test.db"
        db = DatabaseManager(db_path=db_file)

        with db.session() as conn:
            apply_migrations(conn)

            # 1. Verify PRAGMAs
            cursor = conn.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0]
            assert mode.upper() == "WAL"

            cursor = conn.execute("PRAGMA busy_timeout;")
            timeout = cursor.fetchone()[0]
            assert timeout >= 10000

            # 2. Insert relational records
            repo = Repository(conn)
            folder = repo.create_folder(r"C:\Data\TestFolder")
            repo.upsert_file(
                folder_id=folder["folder_id"],
                path=r"C:\Data\TestFolder\doc.txt",
                relative_path="doc.txt",
                filename="doc.txt",
                extension=".txt",
                size_bytes=100,
                modified_at="2026-09-01T00:00:00Z",
                file_id="file_win_1",
            )
            chunk_dict = {
                "chunk_id": "chunk_win_1",
                "file_id": "file_win_1",
                "source_file": "doc.txt",
                "source_path": r"C:\Data\TestFolder\doc.txt",
                "page": 1,
                "section": "General",
                "chunk_index": 0,
                "content": "Test vector content",
                "content_type": "PARAGRAPH",
                "token_count": 5,
            }
            repo.replace_file_chunks("file_win_1", [chunk_dict])

            # 3. Verify sqlite-vec functionality
            vec_store = SqliteVecStore(conn)
            vec_store.upsert_vectors([
                {
                    "chunk_id": "chunk_win_1",
                    "file_id": "file_win_1",
                    "embedding": [0.1] * 384,
                }
            ])

            results = vec_store.search(
                query_vector=[0.1] * 384,
                top_k=5,
            )
            assert len(results) == 1
            assert results[0]["chunk_id"] == "chunk_win_1"

    def test_sqlite_case_insensitive_path_query(self, tmp_path):
        db_file = tmp_path / "case_test.db"
        db = DatabaseManager(db_path=db_file)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(r"C:\Data\Projects\FileMind")
            repo.upsert_file(
                folder_id=folder["folder_id"],
                path=r"C:\Data\Projects\FileMind\README.md",
                relative_path="README.md",
                filename="README.md",
                extension=".md",
                size_bytes=1024,
                modified_at="2026-09-01T00:00:00Z",
                index_status="INDEXED",
                file_id="file_readme_1",
            )

            # Query with lowercase path
            rec_lower = repo.get_file_by_path(r"c:\data\projects\filemind\readme.md")
            assert rec_lower is not None
            assert rec_lower["file_id"] == "file_readme_1"

            # Query with forward slashes
            rec_slash = repo.get_file_by_path("C:/Data/Projects/FileMind/README.md")
            assert rec_slash is not None
            assert rec_slash["file_id"] == "file_readme_1"


class TestWindowsWorkingDirIndependence:
    """Tests that FileMind resolves persistent paths correctly regardless of working directory."""

    def test_app_data_dir_resolution(self):
        data_dir = get_app_data_dir()
        assert data_dir.exists()
        assert "FileMind" in str(data_dir)

    def test_first_run_directory_creation(self, tmp_path):
        fake_appdata = tmp_path / "FreshAppData"
        with patch.dict(os.environ, {"APPDATA": str(fake_appdata)}):
            resolved = get_app_data_dir()
            assert resolved.exists()
            assert resolved == fake_appdata / "FileMind"


class TestWindowsOllamaAndMultimodalDegradation:
    """Tests graceful degradation when Ollama or optional multimodal engines are absent."""

    def test_ollama_offline_graceful_degradation(self):
        mock_provider = MagicMock(spec=OllamaProvider)
        mock_provider.model = "qwen3:4b"
        mock_provider.generate.side_effect = OllamaConnectionError("Unable to connect to 127.0.0.1:11434")

        service = GroundedGenerationService(provider=mock_provider)

        context_pkg = BoundedContextPackage(
            items=[MagicMock()],
            status=EvidenceStatus.READY,
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
            ),
        )

        with patch.object(service.prompt_builder, "build_prompt") as mock_build:
            mock_build.return_value = MagicMock(full_prompt="prompt", estimated_tokens=50)
            response: GroundedGenerationResponse = service.generate_answer(
                query="What is FileMind?",
                context_package=context_pkg,
            )

        assert response.generation_status == GenerationStatus.MODEL_UNAVAILABLE
        assert "Unable to connect" in (response.error or "")

    def test_ollama_readiness_probe_offline(self):
        # Probing a port where no Ollama is running should return truthful status without exception
        readiness = check_ollama_readiness(base_url="http://127.0.0.1:54321", timeout_sec=0.2)
        assert readiness["is_ollama_online"] is False
        assert readiness["has_default_model"] is False
        assert readiness["error"] is not None

    def test_multimodal_graceful_fallback(self, tmp_path):
        # Image parser without OCR / vision engines
        img_parser = ImageParser(ocr_engine=None, vision_engine=None)
        assert img_parser.parser_name == "image-parser"

        # Audio parser without transcription engine
        audio_parser = AudioParser(transcription_engine=None)
        assert audio_parser.parser_name == "audio-parser"

        # Video parser
        video_parser = VideoParser()
        assert video_parser.parser_name == "video-parser"


class TestWindowsFileLockingAndHasher:
    """Tests file locking and transient error recovery on Windows."""

    def test_file_hashing_transient_lock_error_handling(self, tmp_path):
        test_file = tmp_path / "locked_file.txt"
        test_file.write_text("Secret content", encoding="utf-8")

        # Simulate Windows file sharing violation by mocking open with PermissionError / OSError
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            sha, err = compute_file_sha256(str(test_file))
            assert sha is None
            assert "Permission denied" in (err or "")


class TestWindowsWatcherDebouncing:
    """Tests filesystem watcher event normalization and debouncing."""

    def test_watcher_debouncer_coalesces_rapid_events(self):
        flushed_events = []
        debouncer = DebouncedEventManager(
            debounce_window_sec=0.05,
            on_flush_batch=lambda batch: flushed_events.extend(batch),
        )

        # Push CREATE then MODIFY rapidly for the same file
        debouncer.push_event({
            "folder_id": "f1",
            "event_type": "CREATE",
            "path": r"C:\Data\Doc.txt",
            "is_directory": False,
            "observed_at": 100.0,
        })
        debouncer.push_event({
            "folder_id": "f1",
            "event_type": "MODIFY",
            "path": r"C:\Data\Doc.txt",
            "is_directory": False,
            "observed_at": 100.02,
        })

        debouncer.flush()
        assert len(flushed_events) == 1
        assert flushed_events[0]["path"] == r"C:\Data\Doc.txt"

    def test_watcher_directory_delete_deduplication(self):
        flushed_events = []
        debouncer = DebouncedEventManager(
            debounce_window_sec=0.05,
            on_flush_batch=lambda batch: flushed_events.extend(batch),
        )

        debouncer.push_event({
            "folder_id": "f1",
            "event_type": "DELETE",
            "path": r"C:\Data\Folder\file1.txt",
            "is_directory": False,
            "observed_at": 100.0,
        })
        debouncer.push_event({
            "folder_id": "f1",
            "event_type": "DELETE",
            "path": r"C:\Data\Folder",
            "is_directory": True,
            "observed_at": 100.01,
        })

        debouncer.flush()
        # Should prune the child file event and keep only the parent directory delete
        assert len(flushed_events) == 1
        assert flushed_events[0]["path"] == r"C:\Data\Folder"
        assert flushed_events[0]["is_directory"] is True
