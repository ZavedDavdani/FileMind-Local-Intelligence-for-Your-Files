"""
FileMind Persistent Multi-Turn Chat & Conversational RAG Service.

Supports:
- Persistent conversations and messages in SQLite (Migration V10).
- Strict backend-enforced scopes: ALL, FOLDER, FILE.
- Multi-turn conversational context budgeting and sliding window.
- Grounded citation preservation and provenance validation.
- Graceful offline degradation when Ollama is unavailable.
- Auto-titling of new conversations.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.ai.ask_service import AskService
from app.ai.context import (
    BoundedContextPackage,
    ContextBuilder,
    EvidenceStatus,
    default_context_builder,
)
from app.ai.generation import (
    GenerationStatus,
    GroundedGenerationResponse,
    GroundedGenerationService,
    default_generation_service,
)
from app.ai.generation_coordinator import LocalGenerationCoordinator
from app.db.connection import DatabaseManager, db_manager as default_db_manager
from app.db.repository import Repository
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import Reranker
from app.schemas import (
    AskResponse,
    CitationItem,
    ConversationCreate,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationScopeType,
    ChatMessageResponse,
    ModelIdentitySchema,
    SendChatMessageRequest,
)

logger = logging.getLogger("FileMind.AI.ChatService")


class ChatService:
    """Coordinates persistent conversational sessions, scoped retrieval, and grounded multi-turn generation."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        db_manager_instance: Optional[DatabaseManager] = None,
        context_builder: Optional[ContextBuilder] = None,
        generation_service: Optional[GroundedGenerationService] = None,
        embedding_engine: Optional[EmbeddingEngine] = None,
        reranker: Optional[Reranker] = None,
        generation_coordinator: Optional[LocalGenerationCoordinator] = None,
    ):
        self.db_manager = db_manager or db_manager_instance or default_db_manager
        self.context_builder = context_builder or default_context_builder
        self.embedding_engine = embedding_engine
        self.reranker = reranker
        if generation_service is not None:
            self.generation_service = generation_service
        elif generation_coordinator is not None:
            self.generation_service = GroundedGenerationService(
                generation_coordinator=generation_coordinator
            )
        else:
            self.generation_service = default_generation_service

    def create_conversation(self, req: ConversationCreate) -> ConversationResponse:
        """Creates a new persistent conversation with optional scope."""
        scope_type = req.scope_type.value if hasattr(req.scope_type, "value") else str(req.scope_type)
        with self.db_manager.session() as conn:
            repo = Repository(conn)
            # Scope validation
            if scope_type == "FOLDER" and req.scope_id:
                folder = repo.get_folder(req.scope_id)
                if not folder:
                    raise ValueError(f"Scoped folder '{req.scope_id}' does not exist.")
            elif scope_type == "FILE" and req.scope_id:
                file_rec = repo.get_file_by_id(req.scope_id)
                if not file_rec:
                    raise ValueError(f"Scoped file '{req.scope_id}' does not exist.")

            conv = repo.create_conversation(
                title=req.title or "New Conversation",
                scope_type=scope_type,
                scope_id=req.scope_id,
            )
            return ConversationResponse(**conv)

    def list_conversations(self, limit: int = 100, offset: int = 0) -> List[ConversationResponse]:
        """Lists conversations sorted by updated_at descending."""
        with self.db_manager.session() as conn:
            repo = Repository(conn)
            rows = repo.list_conversations(limit=limit, offset=offset)
            return [ConversationResponse(**r) for r in rows]

    def get_conversation_detail(self, conversation_id: str) -> Optional[ConversationDetailResponse]:
        """Retrieves a conversation and all its messages."""
        with self.db_manager.session() as conn:
            repo = Repository(conn)
            conv = repo.get_conversation(conversation_id)
            if not conv:
                return None
            messages_raw = repo.list_chat_messages(conversation_id)
            messages = []
            for m in messages_raw:
                citations_list = [
                    CitationItem(**c) if isinstance(c, dict) else c
                    for c in m.get("citations", [])
                ]
                messages.append(
                    ChatMessageResponse(
                        message_id=m["message_id"],
                        conversation_id=m["conversation_id"],
                        role=m["role"],
                        content=m["content"],
                        citations=citations_list,
                        evidence_status=m.get("evidence_status"),
                        generation_status=m.get("generation_status"),
                        model_identity=m.get("model_identity"),
                        created_at=m["created_at"],
                    )
                )
            return ConversationDetailResponse(
                conversation=ConversationResponse(**conv),
                messages=messages,
            )

    def rename_conversation(self, conversation_id: str, new_title: str) -> Optional[ConversationResponse]:
        """Renames a conversation."""
        with self.db_manager.session() as conn:
            repo = Repository(conn)
            conv = repo.update_conversation_title(conversation_id, new_title)
            if not conv:
                return None
            return ConversationResponse(**conv)

    def delete_conversation(self, conversation_id: str) -> bool:
        """Deletes a conversation and its messages."""
        with self.db_manager.session() as conn:
            repo = Repository(conn)
            return repo.delete_conversation(conversation_id)

    def send_message(
        self,
        conversation_id: str,
        req: SendChatMessageRequest,
    ) -> ChatMessageResponse:
        """
        Executes a conversational turn:
        1. Validates and records the user message.
        2. Resolves conversation scope (ALL / FOLDER / FILE).
        3. Retrieves grounded evidence within scope.
        4. Gathers multi-turn context history.
        5. Generates grounded assistant answer.
        6. Validates citations and persists assistant message.
        7. Auto-updates title if it was 'New Conversation'.
        """
        query_str = req.content.strip()
        if not query_str:
            raise ValueError("Message content cannot be empty.")

        with self.db_manager.session() as conn:
            repo = Repository(conn)
            conv = repo.get_conversation(conversation_id)
            if not conv:
                raise ValueError(f"Conversation '{conversation_id}' not found.")

            # Record user message
            user_msg = repo.add_chat_message(
                conversation_id=conversation_id,
                role="user",
                content=query_str,
            )

            # Auto-title conversation on first user turn if title is default
            if conv["title"] in ("New Conversation", "New Chat") or not conv["title"]:
                clean_title = query_str[:40].replace("\n", " ").strip()
                if len(query_str) > 40:
                    clean_title += "..."
                repo.update_conversation_title(conversation_id, clean_title)

            scope_type = conv.get("scope_type", "ALL")
            scope_id = conv.get("scope_id")

            # Check deterministic chat intent before executing heavy retrieval
            from app.ai.chat_intent import (
                ChatIntent,
                classify_chat_intent,
                format_conversational_response,
                format_metadata_inventory_response,
            )

            intent = classify_chat_intent(query_str)
            if intent == ChatIntent.CONVERSATIONAL:
                bot_text = format_conversational_response(query_str)
                model_id_meta = {
                    "provider": "filemind_local",
                    "model_name": "conversational_assistant",
                    "is_local": True,
                    "model_tag": "local-rules",
                }
                asst_msg = repo.add_chat_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=bot_text,
                    citations=[],
                    evidence_status="SUFFICIENT",
                    generation_status="COMPLETED",
                    model_identity=model_id_meta,
                )
                return ChatMessageResponse(
                    message_id=asst_msg["message_id"],
                    conversation_id=conversation_id,
                    role="assistant",
                    content=asst_msg["content"],
                    citations=[],
                    evidence_status="SUFFICIENT",
                    generation_status="COMPLETED",
                    model_identity=model_id_meta,
                    created_at=asst_msg["created_at"],
                )
            elif intent == ChatIntent.METADATA_INVENTORY:
                bot_text = format_metadata_inventory_response(repo, scope_type, scope_id, query_str)
                model_id_meta = {
                    "provider": "filemind_local",
                    "model_name": "metadata_inventory",
                    "is_local": True,
                    "model_tag": "sqlite-metadata",
                }
                asst_msg = repo.add_chat_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=bot_text,
                    citations=[],
                    evidence_status="SUFFICIENT",
                    generation_status="COMPLETED",
                    model_identity=model_id_meta,
                )
                return ChatMessageResponse(
                    message_id=asst_msg["message_id"],
                    conversation_id=conversation_id,
                    role="assistant",
                    content=asst_msg["content"],
                    citations=[],
                    evidence_status="SUFFICIENT",
                    generation_status="COMPLETED",
                    model_identity=model_id_meta,
                    created_at=asst_msg["created_at"],
                )

            # Scope filters
            filters = {}
            if scope_type == "FOLDER" and scope_id:
                filters["folder_id"] = scope_id
            elif scope_type == "FILE" and scope_id:
                filters["file_id"] = scope_id

            # Execute Hybrid Retrieval within scope
            retriever = HybridRetriever(
                conn,
                embedding_engine=self.embedding_engine,
                reranker=self.reranker,
            )
            mode_lower = (req.mode or "hybrid").lower()
            quality_lower = (req.quality or "fast").lower()
            top_k = req.top_k or 5

            search_res = retriever.search(
                query=query_str,
                top_k=top_k,
                filters=filters,
                mode=mode_lower,
                quality=quality_lower,
            )

            # Gather prior conversation history before current user message
            existing_messages = repo.list_chat_messages(conversation_id, limit=20)
            prior_history = [
                {"role": m["role"], "content": m["content"]}
                for m in existing_messages
                if m.get("message_id") != user_msg["message_id"]
            ]

        candidate_results = search_res.get("results") or []
        candidates = []
        for item in candidate_results:
            if hasattr(item, "model_dump"):
                candidates.append(item.model_dump())
            elif isinstance(item, dict):
                candidates.append(item)
            else:
                candidates.append(dict(item))

        # Build bounded evidence context
        context_pkg: BoundedContextPackage = self.context_builder.build_context(candidates)

        # Grounded Generation (Ollama local inference) with multi-turn history
        gen_resp: GroundedGenerationResponse = self.generation_service.generate_answer(
            query=query_str,
            context_package=context_pkg,
            history=prior_history,
        )

        # Format citations
        citations_out = [
            {
                "citation_id": c.citation_id,
                "chunk_id": c.chunk_id,
                "file_id": c.file_id,
                "source_file": c.source_file,
                "source_path": c.source_path,
                "page": c.page,
                "section": c.section,
                "h1_parent": c.h1_parent,
                "h2_parent": c.h2_parent,
                "line_start": c.line_start,
                "line_end": c.line_end,
                "sheet_name": getattr(c, "sheet_name", None),
                "slide_number": getattr(c, "slide_number", None),
                "time_start": getattr(c, "time_start", None),
                "time_end": getattr(c, "time_end", None),
                "media_type": getattr(c, "media_type", None),
                "score": getattr(c, "score", None),
                "retrieval_method": getattr(c, "retrieval_method", None),
            }
            for c in gen_resp.citations
        ]

        model_identity_dict = {
            "provider": gen_resp.model_identity.provider,
            "model_name": gen_resp.model_identity.model_name,
            "is_local": gen_resp.model_identity.is_local,
            "model_tag": gen_resp.model_identity.model_tag,
        }

        # Persist assistant message
        with self.db_manager.session() as conn:
            repo = Repository(conn)
            asst_msg = repo.add_chat_message(
                conversation_id=conversation_id,
                role="assistant",
                content=gen_resp.answer,
                citations=citations_out,
                evidence_status=context_pkg.status.value,
                generation_status=gen_resp.generation_status.value,
                model_identity=model_identity_dict,
            )

        citations_pydantic = [CitationItem(**c) for c in citations_out]

        return ChatMessageResponse(
            message_id=asst_msg["message_id"],
            conversation_id=conversation_id,
            role="assistant",
            content=asst_msg["content"],
            citations=citations_pydantic,
            evidence_status=context_pkg.status.value,
            generation_status=gen_resp.generation_status.value,
            model_identity=model_identity_dict,
            created_at=asst_msg["created_at"],
        )
