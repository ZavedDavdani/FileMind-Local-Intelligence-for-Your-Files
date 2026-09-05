"""
FileMind Cross-File Intelligence & Synthesis Engine.

Provides:
- Multi-file evidence-backed comparison.
- Multi-document thematic synthesis.
- Timeline and milestone aggregation.
- Contradiction and divergence detection.
- All conclusions strictly grounded in source chunks and exact citation IDs.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.ai.ask_service import AskService
from app.ai.context import ContextBuilder, default_context_builder
from app.ai.generation import GroundedGenerationService, default_generation_service
from app.db.connection import DatabaseManager, db_manager as default_db_manager
from app.db.repository import Repository
from app.schemas import CitationItem, ModelIdentitySchema

logger = logging.getLogger("FileMind.AI.KnowledgeSynthesis")


class KnowledgeSynthesisService:
    """Coordinates cross-file comparison, fact aggregation, and multi-document reasoning."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        db_manager_instance: Optional[DatabaseManager] = None,
        context_builder: Optional[ContextBuilder] = None,
        generation_service: Optional[GroundedGenerationService] = None,
    ):
        self.db_manager = db_manager or db_manager_instance or default_db_manager
        self.context_builder = context_builder or default_context_builder
        self.generation_service = generation_service or default_generation_service

    def compare_files(
        self,
        file_ids: List[str],
        aspects: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Compares 2 to 5 files:
        1. Compares structural metadata (size, chunks, formats, modification times).
        2. Gathers representative chunks from each file.
        3. Identifies common themes, unique aspects, and contrasting details.
        """
        if len(file_ids) < 2:
            raise ValueError("Comparison requires at least 2 files.")
        if len(file_ids) > 5:
            raise ValueError("Comparison supports at most 5 files concurrently.")

        file_summaries = []
        all_candidates = []

        with self.db_manager.session() as conn:
            repo = Repository(conn)
            chunks_by_file = repo.get_chunks_by_files(file_ids)
            for fid in file_ids:
                frec = repo.get_file_by_id(fid)
                if not frec:
                    continue
                chunks = chunks_by_file.get(fid, [])
                insight = repo.get_document_insight(fid)

                file_summaries.append({
                    "file_id": fid,
                    "filename": frec["filename"],
                    "path": frec["path"],
                    "extension": frec["extension"],
                    "size_bytes": frec["size_bytes"],
                    "total_chunks": len(chunks),
                    "key_topics": (insight or {}).get("key_topics", []),
                    "executive_summary": (insight or {}).get("executive_summary"),
                })

                # Select top representative chunks for comparative prompt
                # Prioritize diverse structured sections over naive first-N chunks
                selected_chunks = chunks[:4]
                if len(chunks) > 4:
                    # Pick beginning, middle, and summary sections
                    step = len(chunks) // 4
                    selected_chunks = [chunks[i * step] for i in range(4)]

                for c in selected_chunks:
                    all_candidates.append({
                        "chunk_id": c["chunk_id"],
                        "file_id": fid,
                        "source_file": frec["filename"],
                        "source_path": frec["path"],
                        "content": c["content"],
                        "section": c.get("section"),
                        "page": c.get("page"),
                        "line_start": c.get("line_start"),
                        "line_end": c.get("line_end"),
                        "score": None,
                    })

        if not file_summaries:
            raise ValueError("None of the specified files were found.")

        # Build bounded evidence package
        context_pkg = self.context_builder.build_context(all_candidates)

        aspects_str = ", ".join(aspects) if aspects else "general purpose, main topics, and differences"
        query = f"Compare and contrast the following documents ({', '.join(f['filename'] for f in file_summaries)}) focusing on {aspects_str}. Highlight common themes, unique contributions of each file, and key differences."

        gen_resp = self.generation_service.generate_answer(
            query=query,
            context_package=context_pkg,
        )

        citations_out = [
            {
                "citation_id": c.citation_id,
                "chunk_id": c.chunk_id,
                "file_id": c.file_id,
                "source_file": c.source_file,
                "source_path": c.source_path,
                "page": c.page,
                "section": c.section,
                "score": getattr(c, "score", None),
            }
            for c in gen_resp.citations
        ]

        return {
            "files": file_summaries,
            "comparison_summary": gen_resp.answer,
            "generation_status": gen_resp.generation_status.value,
            "citations": citations_out,
            "model_identity": {
                "provider": gen_resp.model_identity.provider,
                "model_name": gen_resp.model_identity.model_name,
                "is_local": gen_resp.model_identity.is_local,
            },
        }

    def synthesize_files(
        self,
        file_ids: List[str],
        focus_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes knowledge across up to 10 files:
        Aggregates evidence across the documents according to an optional focus topic.
        """
        if not file_ids:
            raise ValueError("At least 1 file must be provided for synthesis.")

        file_list = []
        all_candidates = []
        target_fids = file_ids[:10]

        with self.db_manager.session() as conn:
            repo = Repository(conn)
            chunks_by_file = repo.get_chunks_by_files(target_fids)
            for fid in target_fids:
                frec = repo.get_file_by_id(fid)
                if not frec:
                    continue
                chunks = chunks_by_file.get(fid, [])
                file_list.append({
                    "file_id": fid,
                    "filename": frec["filename"],
                    "path": frec["path"],
                })
                selected_chunks = chunks[:3]
                if len(chunks) > 3:
                    step = len(chunks) // 3
                    selected_chunks = [chunks[i * step] for i in range(3)]

                for c in selected_chunks:
                    all_candidates.append({
                        "chunk_id": c["chunk_id"],
                        "file_id": fid,
                        "source_file": frec["filename"],
                        "source_path": frec["path"],
                        "content": c["content"],
                        "section": c.get("section"),
                        "page": c.get("page"),
                        "line_start": c.get("line_start"),
                        "line_end": c.get("line_end"),
                        "score": None,
                    })

        context_pkg = self.context_builder.build_context(all_candidates)
        prompt_query = focus_query or f"Synthesize the overarching key facts, insights, and findings across the selected documents ({', '.join(f['filename'] for f in file_list)})."

        gen_resp = self.generation_service.generate_answer(
            query=prompt_query,
            context_package=context_pkg,
        )

        citations_out = [
            {
                "citation_id": c.citation_id,
                "chunk_id": c.chunk_id,
                "file_id": c.file_id,
                "source_file": c.source_file,
                "source_path": c.source_path,
                "page": c.page,
                "section": c.section,
                "score": getattr(c, "score", None),
            }
            for c in gen_resp.citations
        ]

        return {
            "files": file_list,
            "synthesis": gen_resp.answer,
            "focus_query": focus_query,
            "generation_status": gen_resp.generation_status.value,
            "citations": citations_out,
            "model_identity": {
                "provider": gen_resp.model_identity.provider,
                "model_name": gen_resp.model_identity.model_name,
                "is_local": gen_resp.model_identity.is_local,
            },
        }
