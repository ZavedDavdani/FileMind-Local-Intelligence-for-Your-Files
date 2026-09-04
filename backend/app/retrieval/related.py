"""
Related Content Service for Phase 5.5 Batch 2.

Discovers and ranks indexed files that are meaningfully related to a source file
by reusing FileMind's hybrid retrieval infrastructure (BM25 + Dense + RRF + Cross-Encoder)
with zero LLM overhead, zero database migrations, and strict self-exclusion.
"""

import logging
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from app.db.connection import DatabaseManager
from app.db.repository import Repository
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger("FileMind.Retrieval.Related")


class RelatedContentService:
    """
    Manages deterministic related file discovery by extracting representative
    signals from an indexed source file and performing hybrid retrieval with
    self-exclusion and file-level Max Chunk Score aggregation.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        retriever: Optional[HybridRetriever] = None,
        embedding_engine: Optional[Any] = None,
        reranker: Optional[Any] = None,
    ):
        self.db = db_manager
        self.retriever = retriever
        self.embedding_engine = embedding_engine
        self.reranker = reranker

    def _build_synthetic_query(
        self,
        file_rec: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        max_chars: int = 400,
    ) -> str:
        """
        Constructs a compact, deterministic synthetic retrieval query from the source file
        using its filename stem, unique section headings, and introductory text snippet.
        Zero LLM invocations.
        """
        query_parts: List[str] = []

        # 1. Filename stem (clean underscores/hyphens into whitespace)
        filename = file_rec.get("filename", "")
        if filename:
            stem = filename.rsplit(".", 1)[0] if "." in filename else filename
            clean_stem = stem.replace("_", " ").replace("-", " ").strip()
            if clean_stem:
                query_parts.append(clean_stem)

        # 2. Unique headings/sections across top chunks
        headings: List[str] = []
        for c in chunks[:15]:
            for field in ("h1_parent", "h2_parent", "section"):
                val = c.get(field)
                if val and val != "General" and val not in headings:
                    headings.append(val)
        if headings:
            query_parts.append(" ".join(headings[:6]))

        # 3. Leading text from earliest content chunks
        intro_texts: List[str] = []
        for c in chunks[:2]:
            content = (c.get("content") or "").strip()
            if content:
                # Clean newlines and take leading text
                cleaned = " ".join(content.split())
                intro_texts.append(cleaned[:180])
        if intro_texts:
            query_parts.append(" ".join(intro_texts))

        full_query = " ".join(query_parts).strip()
        if len(full_query) > max_chars:
            trimmed = full_query[:max_chars].rsplit(" ", 1)[0]
            full_query = trimmed if trimmed else full_query[:max_chars]

        return full_query.strip()

    def _build_explanation(self, file_chunks: List[Dict[str, Any]]) -> str:
        """
        Generates a deterministic, factual explanation describing why a file was matched.
        Mentions matching section headings when available.
        """
        count = len(file_chunks)
        headings: List[str] = []
        for c in file_chunks:
            sec = c.get("section")
            if sec and sec != "General" and sec not in headings:
                headings.append(sec)
            h1 = c.get("h1_parent")
            if h1 and h1 not in headings:
                headings.append(h1)

        if headings:
            top_heading = headings[0]
            if count == 1:
                return f"Matched section '{top_heading}'"
            else:
                return f"Matched {count} sections including '{top_heading}'"
        else:
            if count == 1:
                return "Matched 1 indexed text chunk"
            else:
                return f"Matched {count} indexed text chunks"

    def get_related_files(
        self,
        file_id: str,
        limit: int = 5,
        quality: str = "fast",
    ) -> Dict[str, Any]:
        """
        Retrieves related files for a given file_id.

        Raises:
            ValueError: if source file does not exist or is not indexed.
        """
        quality = (quality or "fast").lower().strip()
        if quality not in ("fast", "quality"):
            raise ValueError(f"Invalid quality mode: '{quality}'. Valid options are 'fast', 'quality'.")

        effective_limit = max(1, min(limit, 50))

        with self.db.session() as conn:
            repo = Repository(conn)
            file_rec = repo.get_file_by_id(file_id)
            if not file_rec:
                raise ValueError(f"File with ID '{file_id}' not found")

            # Check index status
            status = file_rec.get("index_status", "").upper()
            if status != "INDEXED":
                raise ValueError(
                    f"Source file '{file_rec.get('filename')}' is not indexed (status: {status})"
                )

            # Load source file chunks
            chunks = repo.get_chunks_by_file(file_id)
            source_filename = file_rec.get("filename", "Unknown")

            if not chunks:
                return {
                    "source_file_id": file_id,
                    "source_filename": source_filename,
                    "total_found": 0,
                    "retrieval_method": "hybrid",
                    "quality": quality,
                    "query_used": None,
                    "results": [],
                }

            # Build representative synthetic query
            synthetic_query = self._build_synthetic_query(file_rec, chunks)
            if not synthetic_query or len(synthetic_query.strip()) < 2:
                return {
                    "source_file_id": file_id,
                    "source_filename": source_filename,
                    "total_found": 0,
                    "retrieval_method": "hybrid",
                    "quality": quality,
                    "query_used": synthetic_query,
                    "results": [],
                }

            # Candidate pool sizing: ensure enough candidate depth after self-exclusion
            candidate_pool_size = min(max(effective_limit * 5, 30), 100)

            # Execute hybrid retrieval
            retriever = self.retriever or HybridRetriever(
                conn,
                embedding_engine=self.embedding_engine,
                reranker=self.reranker,
            )
            search_resp = retriever.search(
                query=synthetic_query,
                top_k=candidate_pool_size,
                mode="hybrid",
                quality=quality,
            )

            raw_results = search_resp.get("results", [])
            retrieval_method = search_resp.get("retrieval_method", "hybrid")

            # Self-exclusion and file-level grouping
            file_groups: Dict[str, List[Dict[str, Any]]] = {}
            for cand in raw_results:
                cand_fid = cand.get("file_id")
                # Strict self-exclusion guard
                if not cand_fid or cand_fid == file_id:
                    continue
                if cand_fid not in file_groups:
                    file_groups[cand_fid] = []
                file_groups[cand_fid].append(cand)

            if not file_groups:
                return {
                    "source_file_id": file_id,
                    "source_filename": source_filename,
                    "total_found": 0,
                    "retrieval_method": retrieval_method,
                    "quality": quality,
                    "query_used": synthetic_query,
                    "results": [],
                }

            # Batch fetch all candidate file records in a single query
            other_file_ids = list(file_groups.keys())
            batch_file_recs = repo.get_files_by_ids(other_file_ids) if hasattr(repo, "get_files_by_ids") else {}

            # Compute file-level metrics and Max Chunk Score
            ranked_files: List[Dict[str, Any]] = []
            for other_fid, cand_list in file_groups.items():
                # Deterministic candidate chunk sorting: score DESC -> chunk_id ASC
                cand_list.sort(
                    key=lambda x: (
                        -(x.get("score") if x.get("score") is not None else 0.0),
                        str(x.get("chunk_id", "")),
                    )
                )

                primary_cand = cand_list[0]
                supporting_cands = cand_list[1:3]

                # Resolve file metadata from DB if missing in chunk
                other_file_rec = batch_file_recs.get(other_fid) or repo.get_file_by_id(other_fid)
                if other_file_rec:
                    fn = other_file_rec.get("filename", primary_cand.get("source_file", "Unknown"))
                    path = other_file_rec.get("path", primary_cand.get("source_path", ""))
                    rel_path = other_file_rec.get("relative_path")
                    ext = other_file_rec.get("extension")
                    size_bytes = other_file_rec.get("size_bytes", 0)
                else:
                    fn = primary_cand.get("source_file", "Unknown")
                    path = primary_cand.get("source_path", "")
                    rel_path = None
                    ext = f".{fn.rsplit('.', 1)[1]}" if "." in fn else ""
                    size_bytes = 0

                primary_summary = {
                    "chunk_id": primary_cand.get("chunk_id", ""),
                    "section": primary_cand.get("section"),
                    "page": primary_cand.get("page"),
                    "line_start": primary_cand.get("line_start"),
                    "line_end": primary_cand.get("line_end"),
                    "snippet": primary_cand.get("snippet", ""),
                }

                supporting_summaries = [
                    {
                        "chunk_id": sc.get("chunk_id", ""),
                        "section": sc.get("section"),
                        "page": sc.get("page"),
                        "line_start": sc.get("line_start"),
                        "line_end": sc.get("line_end"),
                        "snippet": sc.get("snippet", ""),
                    }
                    for sc in supporting_cands
                ]

                explanation = self._build_explanation(cand_list)
                file_score = float(primary_cand.get("score") or 0.0)

                ranked_files.append({
                    "file_id": other_fid,
                    "filename": fn,
                    "path": path,
                    "relative_path": rel_path,
                    "extension": ext,
                    "size_bytes": size_bytes,
                    "score": round(file_score, 6),
                    "retrieval_method": primary_cand.get("retrieval_method", retrieval_method),
                    "explanation": explanation,
                    "matching_chunk_count": len(cand_list),
                    "primary_matched_chunk": primary_summary,
                    "supporting_chunks": supporting_summaries,
                })

            # Deterministic file ordering: score DESC -> matching_chunk_count DESC -> file_id ASC
            ranked_files.sort(
                key=lambda x: (
                    -x["score"],
                    -x["matching_chunk_count"],
                    x["file_id"],
                )
            )

            final_results = ranked_files[:effective_limit]

            return {
                "source_file_id": file_id,
                "source_filename": source_filename,
                "total_found": len(final_results),
                "retrieval_method": retrieval_method,
                "quality": quality,
                "query_used": synthetic_query,
                "results": final_results,
            }
