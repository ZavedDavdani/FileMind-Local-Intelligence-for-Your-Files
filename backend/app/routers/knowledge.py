"""
Knowledge & Cross-File Intelligence Router for FileMind.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.ai.knowledge_synthesis import KnowledgeSynthesisService
from app.core.context import AppContext
from app.core.deps import get_app_context
from app.db.repository import Repository
from app.schemas import CompareFilesRequest, MultiFileSummaryRequest

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])


def get_synthesis_service(ctx: AppContext = Depends(get_app_context)) -> KnowledgeSynthesisService:
    return KnowledgeSynthesisService(
        db_manager_instance=ctx.db_manager,
    )


@router.post("/compare")
def compare_files(
    req: CompareFilesRequest,
    service: KnowledgeSynthesisService = Depends(get_synthesis_service),
) -> Dict[str, Any]:
    """Performs multi-file evidence-grounded comparative analysis across 2-5 files."""
    try:
        return service.compare_files(file_ids=req.file_ids, aspects=req.aspects)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/synthesize")
def synthesize_files(
    req: MultiFileSummaryRequest,
    service: KnowledgeSynthesisService = Depends(get_synthesis_service),
) -> Dict[str, Any]:
    """Synthesizes key facts, decisions, and themes across multiple documents."""
    try:
        return service.synthesize_files(file_ids=req.file_ids, focus_query=req.focus_query)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/overview")
def get_knowledge_overview(
    ctx: AppContext = Depends(get_app_context),
) -> Dict[str, Any]:
    """Returns top-level knowledge graph / insight metrics for the knowledge workspace."""
    with ctx.db_manager.session() as conn:
        repo = Repository(conn)
        total_files = conn.execute("SELECT COUNT(*) FROM files;").fetchone()[0]
        indexed_files = conn.execute("SELECT COUNT(*) FROM files WHERE index_status = 'INDEXED';").fetchone()[0]
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks;").fetchone()[0]
        total_conversations = conn.execute("SELECT COUNT(*) FROM conversations;").fetchone()[0]
        total_folders = conn.execute("SELECT COUNT(*) FROM folders;").fetchone()[0]

        # Recent insights
        cursor = conn.execute(
            """
            SELECT d.file_id, d.filename, d.executive_summary, d.key_topics_json, d.updated_at
            FROM document_insights d
            ORDER BY d.updated_at DESC
            LIMIT 10;
            """
        )
        recent_insights = []
        for r in cursor.fetchall():
            d = dict(r)
            recent_insights.append(d)

        return {
            "total_files": total_files,
            "indexed_files": indexed_files,
            "total_chunks": total_chunks,
            "total_conversations": total_conversations,
            "total_folders": total_folders,
            "recent_insights": recent_insights,
        }
