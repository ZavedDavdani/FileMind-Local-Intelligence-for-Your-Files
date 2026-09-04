"""AI, Document/Folder Understanding, and Knowledge Connections API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_db
from app.core.errors import map_service_errors
from app.db.connection import DatabaseManager
from app.retrieval.model_registry import ModelType, default_model_registry
from app.schemas import (
    AIStatusResponse,
    AskRequest,
    AskResponse,
    CloudAIStatus,
    ComponentAIStatus,
    DocumentInsightResponse,
    FolderInsightResponse,
    KnowledgeConnectionsResponse,
    LocalAIStatus,
    OllamaReadinessStatus,
)

logger = logging.getLogger("filemind.ai")
router = APIRouter()


@router.get("/ai/status", response_model=AIStatusResponse, tags=["AI Readiness"])
def get_ai_status() -> AIStatusResponse:
    """Returns authoritative readiness status for local AI / retrieval components."""
    emb_model = default_model_registry.get_active_model(ModelType.EMBEDDING)
    rerank_model = default_model_registry.get_active_model(ModelType.RERANKER)

    emb_status = ComponentAIStatus(
        model_name=emb_model.name if emb_model else "sentence-transformers/all-MiniLM-L6-v2",
        provider=emb_model.provider if emb_model else "fastembed",
        dimension=emb_model.dimension if emb_model else 384,
        status=emb_model.readiness.value if emb_model else "unavailable",
        error=emb_model.error if emb_model else None,
    )

    rerank_status = ComponentAIStatus(
        model_name=rerank_model.name if rerank_model else "BAAI/bge-reranker-base",
        provider=rerank_model.provider if rerank_model else "fastembed",
        dimension=None,
        status=rerank_model.readiness.value if rerank_model else "unavailable",
        error=rerank_model.error if rerank_model else None,
    )

    if emb_status.status == "failed" and rerank_status.status == "failed":
        local_status = "failed"
    elif emb_status.status in ("failed", "degraded") or rerank_status.status in ("failed", "degraded"):
        local_status = "degraded"
    elif emb_status.status in ("loading", "downloading", "preparing") or rerank_status.status in ("loading", "downloading", "preparing"):
        local_status = "loading"
    elif emb_status.status == "unavailable" or rerank_status.status == "unavailable":
        local_status = "unavailable"
    else:
        local_status = "ready"

    from app.ai.ollama_provider import check_ollama_readiness
    ollama_info = check_ollama_readiness()
    ollama_status = OllamaReadinessStatus(
        is_ollama_online=ollama_info["is_ollama_online"],
        has_default_model=ollama_info["has_default_model"],
        model_name=ollama_info["model_name"],
        endpoint=ollama_info["endpoint"],
        error=ollama_info.get("error"),
    )

    return AIStatusResponse(
        local_ai=LocalAIStatus(
            status=local_status,
            embedding=emb_status,
            reranker=rerank_status,
            ollama=ollama_status,
        ),
        cloud_ai=CloudAIStatus(
            enabled=False,
            status="unavailable",
        ),
    )


@router.post("/ai/ask", response_model=AskResponse, tags=["Ask FileMind"])
def ask_filemind(req: AskRequest) -> AskResponse:
    """
    End-to-end grounded question-answering endpoint for local files.
    Orchestrates hybrid retrieval, context budgeting, grounded prompt assembly,
    local Ollama generation, and citation validation.
    """
    try:
        from app.ai import default_ask_service
        return default_ask_service.ask(req)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error("Ask FileMind pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )


@router.get("/ai/document-insight/{file_id}", response_model=DocumentInsightResponse, tags=["Document Understanding"])
@map_service_errors(logger, "retrieving document insight", custom_500_detail="An error occurred while retrieving document insight.")
def get_document_insight(file_id: str, db: DatabaseManager = Depends(get_db)) -> DocumentInsightResponse:
    """Retrieves cached document insight or returns NOT_GENERATED/STALE."""
    from app.ai.document_understanding import DocumentUnderstandingService
    svc = DocumentUnderstandingService(db_manager=db)
    res = svc.get_insight(file_id)
    return DocumentInsightResponse(**res)


@router.post("/ai/document-insight/{file_id}/generate", response_model=DocumentInsightResponse, tags=["Document Understanding"])
@map_service_errors(logger, "generating document insight", custom_500_detail="An error occurred while generating document insight.")
def generate_document_insight(file_id: str, db: DatabaseManager = Depends(get_db)) -> DocumentInsightResponse:
    """Generates grounded document understanding with local LLM and stores insight atomically."""
    from app.ai.document_understanding import DocumentUnderstandingService
    svc = DocumentUnderstandingService(db_manager=db)
    res = svc.generate_insight(file_id)
    return DocumentInsightResponse(**res)


@router.get("/ai/folder-insight/{folder_id}", response_model=FolderInsightResponse, tags=["Folder Understanding"])
@map_service_errors(logger, "retrieving folder insight", custom_500_detail="An error occurred while retrieving folder insight.")
def get_folder_insight(folder_id: str, db: DatabaseManager = Depends(get_db)) -> FolderInsightResponse:
    """Retrieves deterministic structural statistics and cached folder AI insight."""
    from app.ai.folder_understanding import FolderUnderstandingService
    svc = FolderUnderstandingService(db_manager=db)
    res = svc.get_folder_insight(folder_id)
    return FolderInsightResponse(**res)


@router.post("/ai/folder-insight/{folder_id}/generate", response_model=FolderInsightResponse, tags=["Folder Understanding"])
@map_service_errors(logger, "generating folder insight", custom_500_detail="An error occurred while generating folder insight.")
def generate_folder_insight(folder_id: str, db: DatabaseManager = Depends(get_db)) -> FolderInsightResponse:
    """Generates grounded folder understanding with local LLM and stores insight atomically."""
    from app.ai.folder_understanding import FolderUnderstandingService
    svc = FolderUnderstandingService(db_manager=db)
    res = svc.generate_insight(folder_id)
    return FolderInsightResponse(**res)


@router.get("/ai/connections/{file_id}", response_model=KnowledgeConnectionsResponse, tags=["Knowledge Connections"])
@map_service_errors(logger, "building knowledge connections", custom_500_detail="An error occurred while building knowledge connections.")
def get_knowledge_connections(file_id: str, db: DatabaseManager = Depends(get_db)) -> KnowledgeConnectionsResponse:
    """Returns dynamic, source-backed topic and file-reference connections."""
    from app.ai.knowledge_connections import KnowledgeConnectionService
    return KnowledgeConnectionsResponse(**KnowledgeConnectionService(db_manager=db).get_connections(file_id))
