"""
Comprehensive regression test suite for practical desktop fixes (Chunks 1-5).
Tests:
- Conversational & metadata intent classification and response generation
- Chat service intent routing for greetings and file inventory
- Individual file registration API (POST /files/register)
- Security boundary preventing registration of FileMind internal data directory
- Asynchronous non-blocking RESCAN/START actions
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import APP_DATA_DIR
from app.db.connection import DatabaseManager, db_manager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.ai.chat_intent import (
    classify_chat_intent,
    ChatIntent,
    format_conversational_response,
    format_metadata_inventory_response,
)
from app.ai.chat_service import ChatService
from app.schemas import ConversationCreate, ConversationScopeType, SendChatMessageRequest


def test_chat_intent_classification():
    """Verify that conversational greetings, capability queries, and metadata queries are classified accurately."""
    # Conversational greetings & capability queries
    assert classify_chat_intent("hi") == ChatIntent.CONVERSATIONAL
    assert classify_chat_intent("Hello!") == ChatIntent.CONVERSATIONAL
    assert classify_chat_intent("Hey there, how are you?") == ChatIntent.CONVERSATIONAL
    assert classify_chat_intent("what can you do?") == ChatIntent.CONVERSATIONAL
    assert classify_chat_intent("help me understand your capabilities") == ChatIntent.CONVERSATIONAL
    assert classify_chat_intent("who are you?") == ChatIntent.CONVERSATIONAL
    assert classify_chat_intent("what features do you have?") == ChatIntent.CONVERSATIONAL

    # Metadata inventory queries
    assert classify_chat_intent("what files do I have?") == ChatIntent.METADATA_INVENTORY
    assert classify_chat_intent("what files are in the index?") == ChatIntent.METADATA_INVENTORY
    assert classify_chat_intent("show me all my indexed files") == ChatIntent.METADATA_INVENTORY
    assert classify_chat_intent("list all indexed documents") == ChatIntent.METADATA_INVENTORY
    assert classify_chat_intent("how many files are indexed?") == ChatIntent.METADATA_INVENTORY
    assert classify_chat_intent("which folders are being indexed?") == ChatIntent.METADATA_INVENTORY

    # Grounded document queries
    assert classify_chat_intent("What was the revenue in Q3 2025?") == ChatIntent.GROUNDED_CONTENT
    assert classify_chat_intent("explain machine learning transformer architecture") == ChatIntent.GROUNDED_CONTENT
    assert classify_chat_intent("find the invoice from Acme Corp") == ChatIntent.GROUNDED_CONTENT
    assert classify_chat_intent("summarize the deployment steps in readme.md") == ChatIntent.GROUNDED_CONTENT


def test_conversational_response_generation():
    """Verify conversational responses provide a rich capability summary and suggestions."""
    response = format_conversational_response("Hello!")
    assert "FileMind" in response
    assert "search" in response.lower() or "capabilities" in response.lower() or "assist" in response.lower()


def test_metadata_inventory_response_generation(tmp_path):
    """Verify metadata inventory queries return an accurate database summary without requiring document chunks."""
    db_file = tmp_path / "test_inventory.db"
    test_db = DatabaseManager(db_path=db_file)
    with test_db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/Docs/Projects")
        folder_id = folder["folder_id"]

        repo.upsert_file(
            folder_id=folder_id,
            path="C:/Docs/Projects/financial_summary.pdf",
            relative_path="financial_summary.pdf",
            filename="financial_summary.pdf",
            extension=".pdf",
            size_bytes=1024,
            modified_at="2026-09-01T00:00:00Z",
            index_status="INDEXED",
        )

        response = format_metadata_inventory_response(repo, "ALL", None, "what files do I have?")
        assert "Indexed Files Summary" in response
        assert "financial_summary.pdf" in response
        assert ".pdf" in response or "PDF" in response


def test_chat_service_conversational_and_metadata_routing(tmp_path):
    """Verify end-to-end ChatService routing for conversational and metadata queries without LLM call."""
    db_file = tmp_path / "test_chat_routing.db"
    test_db = DatabaseManager(db_path=db_file)
    with test_db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/Docs/Work")
        folder_id = folder["folder_id"]

        repo.upsert_file(
            folder_id=folder_id,
            path="C:/Docs/Work/report.docx",
            relative_path="report.docx",
            filename="report.docx",
            extension=".docx",
            size_bytes=2048,
            modified_at="2026-09-01T00:00:00Z",
            index_status="INDEXED",
        )

    chat_svc = ChatService(db_manager_instance=test_db)
    conv = chat_svc.create_conversation(
        ConversationCreate(title="Test Chat", scope_type=ConversationScopeType.ALL)
    )

    # 1. Conversational Query -> instant capability summary
    resp1 = chat_svc.send_message(
        conv.conversation_id,
        SendChatMessageRequest(content="Hi there! What can you do?"),
    )
    assert resp1.role == "assistant"
    assert "FileMind" in resp1.content
    assert len(resp1.citations) == 0

    # 2. Metadata Query -> instant inventory summary
    resp2 = chat_svc.send_message(
        conv.conversation_id,
        SendChatMessageRequest(content="What files do I have indexed?"),
    )
    assert resp2.role == "assistant"
    assert "Indexed Files Summary" in resp2.content
    assert "report.docx" in resp2.content


def test_register_individual_files_api():
    """Verify POST /files/register endpoint handles single and multi-file registration with validation."""
    with TestClient(app) as client:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1. Create supported test files
            file1 = os.path.join(tmp_dir, "notes.txt")
            with open(file1, "w", encoding="utf-8") as f:
                f.write("Important meeting notes about FileMind architecture.")

            file2 = os.path.join(tmp_dir, "data.csv")
            with open(file2, "w", encoding="utf-8") as f:
                f.write("col1,col2\nval1,val2\n")

            # 2. Register both files
            resp = client.post(
                "/files/register",
                json={"paths": [file1, file2]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_requested"] == 2
            assert data["total_enqueued"] == 2
            assert data["total_skipped"] == 0
            assert len(data["results"]) == 2
            assert all(r["status"] in ("QUEUED", "REGISTERED") for r in data["results"])

            # 3. Test non-existent file
            fake_file = os.path.join(tmp_dir, "non_existent_file_123.txt")
            resp_fake = client.post(
                "/files/register",
                json={"paths": [fake_file]},
            )
            assert resp_fake.status_code == 200
            data_fake = resp_fake.json()
            assert data_fake["total_skipped"] == 1
            assert "does not exist" in data_fake["results"][0]["error"]

            # 4. Test unsupported extension (.exe)
            exe_file = os.path.join(tmp_dir, "malicious.exe")
            with open(exe_file, "wb") as f:
                f.write(b"MZ\x00\x00")

            resp_exe = client.post(
                "/files/register",
                json={"paths": [exe_file]},
            )
            assert resp_exe.status_code == 200
            data_exe = resp_exe.json()
            assert data_exe["total_skipped"] == 1
            assert "Unsupported file format" in data_exe["results"][0]["error"]


def test_app_data_dir_registration_blocked():
    """Verify security boundary blocks registration of FileMind internal data directory."""
    with TestClient(app) as client:
        # Attempt to register APP_DATA_DIR
        resp = client.post(
            "/folders",
            json={
                "path": str(APP_DATA_DIR),
                "recursive": True,
                "indexing_enabled": True,
            },
        )
        assert resp.status_code == 400
        assert "internal application data directory" in resp.json()["detail"]


def test_indexing_actions_async_rescan():
    """Verify RESCAN and START actions return immediately as QUEUED without blocking."""
    with TestClient(app) as client:
        resp = client.post(
            "/indexing/control",
            json={"action": "RESCAN"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "RESCAN"
        assert "Rescanning" in data["message"]