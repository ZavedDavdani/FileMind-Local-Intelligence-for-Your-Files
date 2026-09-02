"""
FileMind Phase 5.3 — Ask FileMind End-to-End Orchestration Service.

Wires together Hybrid Retrieval, Quality Reranking, Context Budgeting,
Grounded Prompt Construction, Local Ollama Generation, and Citation Validation
into an authoritative, local-only Question-Answering service.
"""

import logging
import time
from typing import Any, Dict, List, Optional

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
from app.db.connection import db_manager
from app.retrieval.hybrid import HybridRetriever
from app.schemas import (
    AskRequest,
    AskResponse,
    CitationItem,
    ModelIdentitySchema,
    RetrievalMetadata,
)

logger = logging.getLogger("FileMind.AI.AskService")


class AskService:
    """
    Coordinates local hybrid retrieval, context budgeting, and grounded generation for Ask FileMind.
    """

    def __init__(
        self,
        db_manager_instance=None,
        context_builder: Optional[ContextBuilder] = None,
        generation_service: Optional[GroundedGenerationService] = None,
    ):
        self.db_manager = db_manager_instance or db_manager
        self.context_builder = context_builder or default_context_builder
        self.generation_service = generation_service or default_generation_service

    def ask(self, req: AskRequest) -> AskResponse:
        """
        Executes the full Ask FileMind RAG pipeline:
        Query -> Hybrid Retrieval -> Context Assembly -> Grounded Prompt -> Local Ollama -> Citation Validation.
        """
        start_time = time.perf_counter()

        # 1. Validation
        query_str = (req.query or "").strip()
        if not query_str:
            raise ValueError("Query cannot be empty.")
        if len(query_str) > 1000:
            query_str = query_str[:1000]

        mode_lower = (req.mode or "hybrid").lower().strip()
        quality_lower = (req.quality or "fast").lower().strip()

        valid_modes = {"hybrid", "bm25", "dense"}
        valid_qualities = {"fast", "quality"}

        if mode_lower not in valid_modes:
            raise ValueError(f"Invalid retrieval mode '{req.mode}'. Valid options are: 'hybrid', 'bm25', 'dense'.")

        if quality_lower not in valid_qualities:
            raise ValueError(f"Invalid quality mode '{req.quality}'. Valid options are: 'fast', 'quality'.")

        if quality_lower == "quality" and mode_lower != "hybrid":
            raise ValueError(f"Quality mode is only supported with hybrid retrieval (received mode='{req.mode}', quality='{req.quality}').")

        # 2. Retrieval Execution
        filters = {}
        if req.folder_id:
            filters["folder_id"] = req.folder_id
        if req.extension:
            filters["extension"] = req.extension
        if req.file_id:
            filters["file_id"] = req.file_id

        logger.info(
            "Executing Ask retrieval: mode=%s, quality=%s, top_k=%d",
            mode_lower,
            quality_lower,
            req.top_k,
        )

        with self.db_manager.session() as conn:
            retriever = HybridRetriever(conn)
            search_res = retriever.search(
                query=query_str,
                top_k=req.top_k,
                filters=filters,
                mode=mode_lower,
                quality=quality_lower,
            )

        candidate_results = search_res.get("results") or []
        total_found = search_res.get("total_found", len(candidate_results))
        latency_breakdown = search_res.get("latency_breakdown_ms") or {}
        degraded = bool(search_res.get("degraded", False))
        degraded_reason = search_res.get("degraded_reason")

        retrieval_meta = RetrievalMetadata(
            mode=mode_lower,
            quality=quality_lower,
            total_found=total_found,
            latency_breakdown_ms=latency_breakdown,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

        # 3. Context Budget Assembly
        # Convert search candidate items to dictionaries or objects compatible with ContextBuilder
        candidates = []
        for item in candidate_results:
            if hasattr(item, "model_dump"):
                candidates.append(item.model_dump())
            elif isinstance(item, dict):
                candidates.append(item)
            else:
                candidates.append(dict(item))

        context_pkg: BoundedContextPackage = self.context_builder.build_context(candidates)

        logger.info(
            "Assembled bounded context: status=%s, included=%d, omitted=%d, tokens_used=%d",
            context_pkg.status.value,
            context_pkg.budget.candidates_included,
            context_pkg.budget.candidates_omitted,
            context_pkg.budget.evidence_used,
        )

        # 4. Grounded Generation (Includes Grounded Prompt, Local Ollama, and Citation Validation)
        gen_resp: GroundedGenerationResponse = self.generation_service.generate_answer(
            query=query_str,
            context_package=context_pkg,
        )

        # 5. Format Citation Items
        citations_out = [
            CitationItem(
                citation_id=c.citation_id,
                chunk_id=c.chunk_id,
                file_id=c.file_id,
                source_file=c.source_file,
                source_path=c.source_path,
                page=c.page,
                section=c.section,
                h1_parent=c.h1_parent,
                h2_parent=c.h2_parent,
                line_start=c.line_start,
                line_end=c.line_end,
                char_start=c.char_start,
                char_end=c.char_end,
                content_hash=c.content_hash,
                score=c.score,
                reranker_score=c.reranker_score,
                retrieval_method=c.retrieval_method,
            )
            for c in gen_resp.citations
        ]

        model_ident = ModelIdentitySchema(
            provider=gen_resp.model_identity.provider,
            model_name=gen_resp.model_identity.model_name,
            is_local=gen_resp.model_identity.is_local,
            model_tag=gen_resp.model_identity.model_tag,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "Ask completed: gen_status=%s, citations=%d, latency=%.1fms",
            gen_resp.generation_status.value,
            len(citations_out),
            elapsed_ms,
        )

        return AskResponse(
            answer=gen_resp.answer,
            query=query_str,
            generation_status=gen_resp.generation_status.value,
            evidence_status=gen_resp.evidence_status.value,
            citations=citations_out,
            unresolved_citations=gen_resp.unresolved_citations,
            model_identity=model_ident,
            retrieval_metadata=retrieval_meta,
            context_budget=gen_resp.context_budget.to_dict(),
            error=gen_resp.error,
        )


# Global default AskService instance
default_ask_service = AskService()
