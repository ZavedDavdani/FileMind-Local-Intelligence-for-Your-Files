"""
Regression test suite for Remediation Chunk 3 (Findings 13-18).
- Finding 13: Magic-byte header inspection precedence in detector.py.
- Finding 14 & 17: VideoParser audio extraction & truthful transcription/metadata.
- Finding 15: DatabaseManager poisoned connection discard upon rollback failure.
- Finding 16: ExportService safe Markdown formatting with score=None.
- Finding 18: ChatRepository deterministic message ordering with secondary tiebreaker.
"""

import os
import sqlite3
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from app.intelligence.detector import detect_file_format, is_supported_document
from app.intelligence.parsers.video_parser import VideoParser
from app.intelligence.parsers.audio_parser import BaseTranscriptionEngine
from app.intelligence.models import ElementType
from app.db.connection import DatabaseManager
from app.db.repositories.chat import ChatRepository
from app.ai.export_service import ExportService


def test_finding13_magic_byte_precedence(tmp_path):
    """Header magic bytes should take precedence over missing or misleading extensions."""
    # 1. PDF with .bin extension
    pdf_file = tmp_path / "sample_doc.bin"
    pdf_file.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n")
    mime, fmt = detect_file_format(str(pdf_file))
    assert mime == "application/pdf"
    assert fmt == "PDF"
    assert is_supported_document(str(pdf_file)) is True

    # 2. PNG with .dat extension
    png_file = tmp_path / "sample_img.dat"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    mime_png, fmt_png = detect_file_format(str(png_file))
    assert mime_png == "image/png"
    assert fmt_png == "IMAGE"

    # 3. SQLite format
    sqlite_file = tmp_path / "custom.db"
    sqlite_file.write_bytes(b"SQLite format 3\x00\x10\x00\x01\x01")
    mime_sql, fmt_sql = detect_file_format(str(sqlite_file))
    assert mime_sql == "application/x-sqlite3"

    # 4. Fallback to extension when magic bytes absent
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("Plain text content")
    mime_txt, fmt_txt = detect_file_format(str(txt_file))
    assert mime_txt == "text/plain"
    assert fmt_txt == "TEXT"


def test_finding14_and_17_video_parser_transcription_and_honesty(tmp_path):
    """VideoParser should support audio transcription and honestly represent metadata without fake captions."""
    dummy_video = tmp_path / "presentation.mp4"
    dummy_video.write_bytes(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00isommp42")

    # 1. Without transcription engine
    parser_no_tx = VideoParser()
    doc_no_tx = parser_no_tx.parse(str(dummy_video), file_id="vid_1")
    assert len(doc_no_tx.elements) == 1
    assert doc_no_tx.elements[0].element_type == ElementType.VISUAL_METADATA
    assert "IMAGE_CAPTION" not in doc_no_tx.full_text

    # 2. With transcription engine
    mock_tx = MagicMock(spec=BaseTranscriptionEngine)
    mock_tx.transcribe.return_value = [
        {"start": 0.0, "end": 4.5, "text": "Welcome to the FileMind architecture demo."},
        {"start": 5.0, "end": 9.2, "text": "Today we cover local-first indexing."},
    ]
    parser_with_tx = VideoParser(transcription_engine=mock_tx)
    doc_with_tx = parser_with_tx.parse(str(dummy_video), file_id="vid_2")

    transcript_elems = [e for e in doc_with_tx.elements if e.element_type == ElementType.TRANSCRIPT_SEGMENT]
    assert len(transcript_elems) == 2
    assert "Welcome to the FileMind architecture demo." in transcript_elems[0].text
    assert transcript_elems[0].time_start == 0.0
    assert transcript_elems[0].time_end == 4.5
    assert transcript_elems[0].extraction_method == "transcription"


def test_finding15_pooled_connection_discard_on_poison(tmp_path):
    """Poisoned connection must be closed and discarded from pool if rollback fails."""
    db_file = tmp_path / "test_pool.db"
    mgr = DatabaseManager(db_path=db_file, pooled=True)

    # Place a mock connection in _local.connections that fails on rollback
    mock_conn = MagicMock()
    mock_conn.rollback.side_effect = sqlite3.OperationalError("Disk I/O error during rollback")
    mgr._local.connections = {str(mgr.db_path): mock_conn}

    with pytest.raises(Exception):
        with mgr.session() as conn:
            raise RuntimeError("Simulated transaction crash")

    # Verify that close_thread_connection was called and mock_conn was discarded from thread-local pool
    assert str(mgr.db_path) not in getattr(mgr._local, "connections", {})
    mock_conn.close.assert_called()

    # Next call to get_connection creates a fresh real connection
    fresh_conn = mgr.get_connection()
    assert fresh_conn is not mock_conn
    mgr.close_all()


def test_finding16_export_search_markdown_none_score():
    """export_search_markdown must handle score=None without crashing."""
    results = [
        {
            "source_file": "report.pdf",
            "score": 0.9542,
            "snippet": "High relevance finding.",
            "page": 3,
            "section": "Executive Summary",
        },
        {
            "source_file": "unranked_note.txt",
            "score": None,
            "snippet": "Synthesis synthesized note without rank.",
            "page": None,
            "section": None,
        },
        {
            "filename": "backup.docx",
            "snippet": "Missing score field altogether.",
        },
    ]

    md = ExportService.export_search_markdown(query="quarterly roadmap", results=results)
    assert "# FileMind Search Evidence: \"quarterly roadmap\"" in md
    assert "Score: 0.954" in md
    assert "Unranked" in md
    assert "report.pdf" in md
    assert "unranked_note.txt" in md
    assert "backup.docx" in md


def test_finding18_deterministic_chat_message_ordering(tmp_path):
    """Chat messages inserted with identical timestamps must order deterministically by message_id."""
    db_file = tmp_path / "test_chat.db"
    mgr = DatabaseManager(db_path=db_file, pooled=False)

    with mgr.session() as conn:
        conn.execute(
            """
            CREATE TABLE conversations (
                conversation_id TEXT PRIMARY KEY,
                title TEXT,
                scope_type TEXT,
                scope_id TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE chat_messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                role TEXT,
                content TEXT,
                citations TEXT,
                evidence_status TEXT,
                generation_status TEXT,
                model_identity TEXT,
                created_at TEXT
            );
            """
        )

        repo = ChatRepository(conn)
        repo.create_conversation(title="Test Conv", conversation_id="c1")

        # Insert 4 messages with the exact same timestamp but distinct message IDs
        same_ts = "2026-09-05T12:00:00.000000Z"
        for mid in ["msg_d", "msg_b", "msg_a", "msg_c"]:
            conn.execute(
                """
                INSERT INTO chat_messages (message_id, conversation_id, role, content, created_at)
                VALUES (?, 'c1', 'user', ?, ?);
                """,
                (mid, f"Content for {mid}", same_ts),
            )

        messages = repo.list_chat_messages("c1")
        mids = [m["message_id"] for m in messages]
        # Ordering must be deterministically sorted by created_at ASC, message_id ASC
        assert mids == ["msg_a", "msg_b", "msg_c", "msg_d"]
