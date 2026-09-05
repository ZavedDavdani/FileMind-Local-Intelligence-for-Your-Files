"""
Chat Router for FileMind Phase 6 Persistent Conversational Workspaces.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.ai.chat_service import ChatService
from app.core.context import AppContext
from app.core.deps import get_app_context
from app.schemas import (
    ChatMessageResponse,
    ConversationCreate,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationUpdate,
    SendChatMessageRequest,
)

router = APIRouter(prefix="/api/chat", tags=["Chat"])


def get_chat_service(ctx: AppContext = Depends(get_app_context)) -> ChatService:
    """Dependency provider for ChatService initialized with shared app context."""
    return ChatService(
        db_manager_instance=ctx.db_manager,
        embedding_engine=getattr(ctx, "embedding_engine", None),
        reranker=getattr(ctx, "reranker", None),
        generation_coordinator=getattr(ctx, "generation_coordinator", None),
    )


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    req: ConversationCreate,
    service: ChatService = Depends(get_chat_service),
) -> ConversationResponse:
    """Creates a new persistent conversation with optional scope (ALL, FOLDER, FILE)."""
    try:
        return service.create_conversation(req)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/conversations", response_model=List[ConversationResponse])
def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: ChatService = Depends(get_chat_service),
) -> List[ConversationResponse]:
    """Lists persistent conversations ordered by most recently updated."""
    return service.list_conversations(limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: str,
    service: ChatService = Depends(get_chat_service),
) -> ConversationDetailResponse:
    """Retrieves conversation metadata and all associated messages."""
    detail = service.get_conversation_detail(conversation_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return detail


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
def rename_conversation(
    conversation_id: str,
    req: ConversationUpdate,
    service: ChatService = Depends(get_chat_service),
) -> ConversationResponse:
    """Renames an existing conversation."""
    if not req.title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title cannot be empty")
    conv = service.rename_conversation(conversation_id, req.title)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    service: ChatService = Depends(get_chat_service),
):
    """Deletes a conversation and its messages."""
    deleted = service.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


@router.post("/conversations/{conversation_id}/messages", response_model=ChatMessageResponse)
def send_message(
    conversation_id: str,
    req: SendChatMessageRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    """Sends a user query into a conversation, executes scoped RAG, and returns grounded answer with citations."""
    try:
        return service.send_message(conversation_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
