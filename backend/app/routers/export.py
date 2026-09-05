"""
Export Router for FileMind Evidence & Knowledge Export.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.ai.export_service import ExportService
from app.core.context import AppContext
from app.core.deps import get_app_context
from app.db.repository import Repository
from app.schemas import ExportConversationRequest, ExportResponse, ExportSearchRequest

router = APIRouter(prefix="/api/export", tags=["Export"])


@router.post("/conversation/{conversation_id}", response_model=ExportResponse)
def export_conversation(
    conversation_id: str,
    req: ExportConversationRequest,
    ctx: AppContext = Depends(get_app_context),
) -> ExportResponse:
    """Exports a persistent conversation to Markdown, JSON, or Plain Text."""
    with ctx.db_manager.session() as conn:
        repo = Repository(conn)
        conv = repo.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        messages = repo.list_chat_messages(conversation_id)

    fmt = req.format.value if hasattr(req.format, "value") else str(req.format)
    clean_title = "".join(c for c in conv["title"] if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")

    if fmt == "json":
        content_str = ExportService.export_conversation_json(conv, messages)
        filename = f"filemind_chat_{clean_title}_{conversation_id[:8]}.json"
        content_type = "application/json"
    elif fmt == "text":
        content_str = ExportService.export_conversation_text(conv, messages)
        filename = f"filemind_chat_{clean_title}_{conversation_id[:8]}.txt"
        content_type = "text/plain"
    else:
        content_str = ExportService.export_conversation_markdown(
            conv,
            messages,
            include_citations=req.include_citations,
            include_timestamps=req.include_timestamps,
        )
        filename = f"filemind_chat_{clean_title}_{conversation_id[:8]}.md"
        content_type = "text/markdown"

    return ExportResponse(
        format=fmt,
        filename=filename,
        content_type=content_type,
        content=content_str,
    )


@router.post("/search", response_model=ExportResponse)
def export_search_results(
    req: ExportSearchRequest,
) -> ExportResponse:
    """Exports search results with citations to Markdown or JSON."""
    fmt = req.format.value if hasattr(req.format, "value") else str(req.format)
    if fmt == "json":
        import json
        content_str = json.dumps({"query": req.query, "results": req.results}, indent=2)
        filename = "filemind_search_evidence.json"
        content_type = "application/json"
    else:
        content_str = ExportService.export_search_markdown(req.query, req.results)
        filename = "filemind_search_evidence.md"
        content_type = "text/markdown"

    return ExportResponse(
        format=fmt,
        filename=filename,
        content_type=content_type,
        content=content_str,
    )
