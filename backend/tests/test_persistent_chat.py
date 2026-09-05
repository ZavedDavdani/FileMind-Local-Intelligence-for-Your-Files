"""
Tests for FileMind Persistent Chat & Conversational RAG Engine.
"""

import os
import pytest
from unittest.mock import MagicMock

from app.ai.chat_service import ChatService
from app.ai.generation import GroundedGenerationService
from app.ai.ollama_provider import OllamaConnectionError, OllamaProvider, OllamaResponse
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.schemas import (
    ConversationCreate,
    ConversationScopeType,
    ConversationUpdate,
    SendChatMessageRequest,
)


@pytest.fixture
def chat_env(tmp_path):
    db_file = tmp_path / "chat_test.db"
    db = DatabaseManager(db_path=db_file)
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\Work\ProjectAlpha")
        folder_id = folder["folder_id"]

        f1 = repo.upsert_file(
            folder_id=folder_id,
            path=r"C:\Work\ProjectAlpha\architecture.md",
            relative_path="architecture.md",
            filename="architecture.md",
            extension=".md",
            size_bytes=1200,
            modified_at="2026-09-01T00:00:00Z",
            file_id="f_alpha_arch",
        )
        repo.replace_file_chunks(
            file_id="f_alpha_arch",
            chunks=[
                {
                    "chunk_id": "chk_alpha_1",
                    "file_id": "f_alpha_arch",
                    "source_file": "architecture.md",
                    "source_path": r"C:\Work\ProjectAlpha\architecture.md",
                    "page": 1,
                    "section": "Core Engine",
                    "h1_parent": "Architecture",
                    "h2_parent": "Core Engine",
                    "line_start": 1,
                    "line_end": 10,
                    "char_start": 0,
                    "char_end": 200,
                    "content_hash": "hash1",
                    "chunk_index": 0,
                    "parser_name": "markdown-parser",
                    "parser_version": "1.0",
                    "chunker_version": "v1",
                    "content": "Project Alpha core engine is implemented entirely in Rust and SQLite with local embeddings.",
                    "content_type": "text",
                    "token_count": 15,
                    "metadata": {},
                }
            ],
        )
        repo.update_file_status("f_alpha_arch", "INDEXED")

    return db, folder_id, "f_alpha_arch"


def test_conversation_lifecycle(chat_env):
    db, folder_id, file_id = chat_env
    chat_svc = ChatService(db_manager_instance=db)

    # 1. Create global conversation
    c1 = chat_svc.create_conversation(
        ConversationCreate(title="General Chat", scope_type=ConversationScopeType.ALL)
    )
    assert c1.title == "General Chat"
    assert c1.scope_type == "ALL"

    # 2. Create scoped conversation (Folder)
    c2 = chat_svc.create_conversation(
        ConversationCreate(title="Folder Chat", scope_type=ConversationScopeType.FOLDER, scope_id=folder_id)
    )
    assert c2.scope_type == "FOLDER"
    assert c2.scope_id == folder_id

    # 3. Create scoped conversation (File)
    c3 = chat_svc.create_conversation(
        ConversationCreate(title="File Chat", scope_type=ConversationScopeType.FILE, scope_id=file_id)
    )
    assert c3.scope_type == "FILE"
    assert c3.scope_id == file_id

    # 4. List conversations
    convs = chat_svc.list_conversations()
    assert len(convs) == 3

    # 5. Rename
    renamed = chat_svc.rename_conversation(c1.conversation_id, "Renamed Global Chat")
    assert renamed.title == "Renamed Global Chat"

    # 6. Delete
    deleted = chat_svc.delete_conversation(c3.conversation_id)
    assert deleted is True
    assert len(chat_svc.list_conversations()) == 2


def test_multi_turn_chat_with_grounded_response_and_persistence(chat_env):
    db, folder_id, file_id = chat_env

    # Mock Ollama provider with grounded citation response
    mock_provider = MagicMock(spec=OllamaProvider)
    mock_provider.model = "qwen3:4b"
    mock_provider.generate.return_value = OllamaResponse(
        model="qwen3:4b",
        response="Project Alpha core engine is implemented in Rust and SQLite [E1].",
        done=True,
        done_reason="stop",
        prompt_eval_count=100,
        eval_count=25,
    )

    gen_service = GroundedGenerationService(provider=mock_provider)
    chat_svc = ChatService(
        db_manager_instance=db,
        generation_service=gen_service,
    )

    conv = chat_svc.create_conversation(
        ConversationCreate(title="New Conversation", scope_type=ConversationScopeType.FOLDER, scope_id=folder_id)
    )

    # Turn 1
    resp1 = chat_svc.send_message(
        conv.conversation_id,
        SendChatMessageRequest(content="Project Alpha architecture SQLite"),
    )
    assert resp1.role == "assistant"
    assert "Rust and SQLite" in resp1.content
    assert len(resp1.citations) >= 1
    assert resp1.citations[0].citation_id == "E1"
    assert resp1.citations[0].source_file == "architecture.md"

    # Verify auto-titling happened
    detail = chat_svc.get_conversation_detail(conv.conversation_id)
    assert detail.conversation.title != "New Conversation"
    assert len(detail.messages) == 2  # user + assistant

    # Turn 2
    mock_provider.generate.return_value = OllamaResponse(
        model="qwen3:4b",
        response="Yes, local embeddings are used alongside SQLite [E1].",
        done=True,
        done_reason="stop",
        prompt_eval_count=120,
        eval_count=20,
    )
    resp2 = chat_svc.send_message(
        conv.conversation_id,
        SendChatMessageRequest(content="Project Alpha local embeddings"),
    )
    assert "local embeddings" in resp2.content

    # Verify message sequence across DB recreation (persistence)
    fresh_db = DatabaseManager(db_path=db.db_path)
    fresh_chat_svc = ChatService(db_manager_instance=fresh_db)
    final_detail = fresh_chat_svc.get_conversation_detail(conv.conversation_id)
    assert len(final_detail.messages) == 4
    assert final_detail.messages[0].role == "user"
    assert final_detail.messages[1].role == "assistant"
    assert final_detail.messages[2].role == "user"
    assert final_detail.messages[3].role == "assistant"


def test_chat_offline_ollama_graceful_degradation(chat_env):
    db, folder_id, file_id = chat_env

    mock_provider = MagicMock(spec=OllamaProvider)
    mock_provider.model = "qwen3:4b"
    mock_provider.generate.side_effect = OllamaConnectionError("Cannot connect to Ollama")

    gen_service = GroundedGenerationService(provider=mock_provider)
    chat_svc = ChatService(
        db_manager_instance=db,
        generation_service=gen_service,
    )

    conv = chat_svc.create_conversation(
        ConversationCreate(title="Offline Chat", scope_type=ConversationScopeType.ALL)
    )

    resp = chat_svc.send_message(
        conv.conversation_id,
        SendChatMessageRequest(content="Project Alpha SQLite"),
    )
    assert resp.generation_status in ("MODEL_UNAVAILABLE", "NO_EVIDENCE")
    assert "local ai model is not currently available" in resp.content.lower() or resp.generation_status == "MODEL_UNAVAILABLE"
