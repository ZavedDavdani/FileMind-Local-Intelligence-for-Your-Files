"""
Tests for Model Management, Settings, Storage Stats, Diagnostics, and Export.
"""

from app.ai.export_service import ExportService
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.routers.settings import get_diagnostics, get_storage_stats
from app.schemas import ExportFormat


def test_export_service_markdown_json_text():
    conv = {
        "conversation_id": "conv_123",
        "title": "Release Planning",
        "scope_type": "FOLDER",
        "scope_id": "fold_1",
    }
    messages = [
        {
            "role": "user",
            "content": "What are our release milestones?",
            "created_at": "2026-09-05T10:00:00Z",
        },
        {
            "role": "assistant",
            "content": "Milestone 1 is Gate 1 and Milestone 2 is Release [E1].",
            "created_at": "2026-09-05T10:00:05Z",
            "citations": [
                {
                    "citation_id": "E1",
                    "source_file": "roadmap.md",
                    "section": "Timeline",
                    "page": 2,
                }
            ],
        },
    ]

    # 1. Markdown Export
    md_out = ExportService.export_conversation_markdown(conv, messages)
    assert "# FileMind Conversation: Release Planning" in md_out
    assert "**[E1]** `roadmap.md`" in md_out
    assert "Milestone 1 is Gate 1" in md_out

    # 2. JSON Export
    json_out = ExportService.export_conversation_json(conv, messages)
    assert '"title": "Release Planning"' in json_out
    assert '"generator": "FileMind v0.1.0"' in json_out

    # 3. Text Export
    txt_out = ExportService.export_conversation_text(conv, messages)
    assert "FILEMIND CONVERSATION: Release Planning" in txt_out
    assert "[USER]" in txt_out
    assert "[FILEMIND]" in txt_out


def test_storage_and_diagnostics_contracts(tmp_path):
    db_file = tmp_path / "diag_test.db"
    db = DatabaseManager(db_path=db_file)
    with db.session() as conn:
        apply_migrations(conn)

    mock_ctx = type("MockCtx", (), {"db_manager": db})()
    diag = get_diagnostics(ctx=mock_ctx)
    assert diag.version == "0.1.0"
    assert diag.database_status == "healthy"
    assert diag.uptime_seconds >= 0

    storage = get_storage_stats(ctx=mock_ctx)
    assert storage.total_files_indexed == 0
    assert storage.total_chunks == 0
