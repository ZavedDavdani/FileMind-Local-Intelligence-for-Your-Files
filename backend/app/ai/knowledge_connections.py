"""Dynamic, source-backed knowledge connections for Batch 3.2 & optimization.

Connections are intentionally not persisted: every response is reconstructed
from the current file records, chunks, and valid Document Insight cache.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from app.ai.document_understanding import DocumentUnderstandingService
from app.core.config import OLLAMA_MODEL
from app.db.connection import DatabaseManager
from app.db.repository import Repository


def _topic_key(topic: str) -> str:
    return " ".join(str(topic).casefold().split())


def _filter_evidence_for_topic(citations: List[Dict[str, Any]], topic: str) -> List[Dict[str, Any]]:
    if not citations:
        return []
    topic_words = {w for w in topic.casefold().split() if len(w) > 2}
    if not topic_words:
        return citations
    matched = []
    for c in citations:
        text = f"{c.get('section', '')} {c.get('snippet', '')} {c.get('h1_parent', '')} {c.get('h2_parent', '')}".casefold()
        if any(w in text for w in topic_words):
            matched.append(c)
    return matched if matched else citations


class KnowledgeConnectionService:
    """Builds explainable shared-topic and exact file-reference links.

    Behavior-preserving rewrite: batches per-file DB lookups and precomputes
    a single reference target list instead of an O(chunks x files) unbatched scan.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    @staticmethod
    def _file_view(file_rec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "file_id": file_rec["file_id"],
            "filename": file_rec["filename"],
            "path": file_rec["path"],
            "relative_path": file_rec.get("relative_path"),
            "content_hash": file_rec.get("sha256"),
        }

    @staticmethod
    def _chunk_evidence(chunk: Dict[str, Any], file_rec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "chunk_id": chunk["chunk_id"],
            "file_id": file_rec["file_id"],
            "source_file": file_rec["filename"],
            "source_path": file_rec["path"],
            "content_hash": chunk.get("content_hash"),
            "page": chunk.get("page"),
            "section": chunk.get("section"),
            "line_start": chunk.get("line_start"),
            "line_end": chunk.get("line_end"),
        }

    @staticmethod
    def _contains_exact_reference(content: str, reference: str) -> bool:
        """Case-insensitive literal matching with filename/path boundaries."""
        value = reference.replace("\\", "/").strip()
        if not value:
            return False
        escaped = re.escape(value)
        return bool(
            re.search(r"(?<![\w./-])" + escaped + r"(?![\w./-])", content.replace("\\", "/"), re.I)
        )

    def _current_topic_insights_batch(
        self, repo: Repository, files: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Batched replacement for per-file insight, chunk, and citation queries."""
        file_ids = [f["file_id"] for f in files]
        insights_by_file = repo.get_document_insights_by_files(file_ids, model_name=OLLAMA_MODEL)
        chunks_by_file = repo.get_chunks_by_files(file_ids)

        # Batch-fetch every citation's chunk in one query instead of one-by-one.
        all_citation_ids: Set[str] = set()
        for insight in insights_by_file.values():
            for citation in insight.get("citations") or []:
                if citation.get("chunk_id"):
                    all_citation_ids.add(citation["chunk_id"])
        chunks_by_id = repo.get_chunks_by_ids(list(all_citation_ids)) if all_citation_ids else {}

        result: Dict[str, Dict[str, Any]] = {}
        by_id = {f["file_id"]: f for f in files}
        for file_id, insight in insights_by_file.items():
            file_rec = by_id.get(file_id)
            chunks = chunks_by_file.get(file_id, [])
            if not file_rec or not insight:
                continue
            if not DocumentUnderstandingService.is_cached_insight_current(
                file_rec, chunks, insight, OLLAMA_MODEL
            ):
                continue
            citations = []
            for citation in insight.get("citations") or []:
                chunk = chunks_by_id.get(citation.get("chunk_id"))
                if chunk and chunk.get("file_id") == file_id and citation.get(
                    "content_hash"
                ) == chunk.get("content_hash"):
                    citations.append(citation)
            if not citations:
                continue
            result[file_id] = {"topics": insight.get("key_topics") or [], "citations": citations}
        return result

    def get_connections(self, file_id: str) -> Dict[str, Any]:
        with self.db.session() as conn:
            repo = Repository(conn)
            source = repo.get_file_by_id(file_id)
            if not source:
                raise ValueError(f"File with ID {file_id} not found")
            if source.get("index_status") != "INDEXED":
                return {"source_file": self._file_view(source), "connections": []}

            # --- shared-topic connections: query only files with cached insights for active model ---
            cursor = conn.execute(
                """
                SELECT DISTINCT f.file_id, f.folder_id, f.path, f.filename, f.relative_path, f.extension, f.size_bytes, f.sha256, f.index_status
                FROM files f
                JOIN document_insights di ON di.file_id = f.file_id
                WHERE f.index_status = 'INDEXED' AND di.status = 'READY' AND di.model_name = ?;
                """,
                (OLLAMA_MODEL,),
            )
            files_with_insights = [dict(r) for r in cursor.fetchall()]
            if not any(f["file_id"] == file_id for f in files_with_insights):
                files_with_insights.append(source)

            connections: List[Dict[str, Any]] = []
            seen: Set[tuple[str, str, str]] = set()

            insights_by_file = self._current_topic_insights_batch(repo, files_with_insights)
            source_insight = insights_by_file.get(file_id)
            if source_insight:
                source_topics = {_topic_key(t): str(t).strip() for t in source_insight["topics"] if _topic_key(t)}
                for target in files_with_insights:
                    if target["file_id"] == file_id:
                        continue
                    target_insight = insights_by_file.get(target["file_id"])
                    if not target_insight:
                        continue
                    target_topics = {_topic_key(t) for t in target_insight["topics"] if _topic_key(t)}
                    for key in sorted(set(source_topics) & target_topics):
                        dedup = ("shared_topic", target["file_id"], key)
                        if dedup in seen:
                            continue
                        seen.add(dedup)
                        topic_label = source_topics[key]
                        connections.append({
                            "connection_type": "shared_topic",
                            "label": topic_label,
                            "explanation": f"Both files have the current grounded topic ‘{topic_label}’.",
                            "target_file": self._file_view(target),
                            "source_evidence": _filter_evidence_for_topic(source_insight["citations"], topic_label),
                            "target_evidence": _filter_evidence_for_topic(target_insight["citations"], topic_label),
                        })

            # --- file-reference connections: single pass against indexed file candidates ---
            indexed_candidates = [f for f in repo.list_files(status="INDEXED", limit=100000) if f["file_id"] != file_id]
            filename_counts: Dict[str, int] = {}
            for f in indexed_candidates + [source]:
                name = (f.get("filename") or "").casefold()
                if name:
                    filename_counts[name] = filename_counts.get(name, 0) + 1

            # Build the candidate reference list ONCE (not per chunk).
            reference_targets = []  # (relative, filename_if_unique, target_rec)
            for target in indexed_candidates:
                relative = (target.get("relative_path") or "").replace("\\", "/")
                filename = target.get("filename") or ""
                unique_filename = filename if filename_counts.get(filename.casefold(), 0) == 1 else None
                reference_targets.append((relative, unique_filename, target))

            reference_candidates: Dict[str, tuple[int, int, str, Dict[str, Any], str]] = {}
            for chunk in repo.get_chunks_by_file(file_id):
                content = chunk.get("content") or ""
                if not content:
                    continue
                content_normalized = content.replace("\\", "/").casefold()
                for relative, unique_filename, target in reference_targets:
                    references = [r for r in (relative, unique_filename) if r]
                    matched = None
                    for r in references:
                        r_norm = r.replace("\\", "/").casefold()
                        if r_norm in content_normalized and self._contains_exact_reference(content, r):
                            matched = r
                            break
                    if not matched:
                        continue
                    rank = 0 if matched == relative else 1
                    candidate = (rank, int(chunk.get("chunk_index") or 0), chunk["chunk_id"], chunk, matched)
                    existing = reference_candidates.get(target["file_id"])
                    if existing is None or candidate[:3] < existing[:3]:
                        reference_candidates[target["file_id"]] = candidate

            indexed_by_id = {f["file_id"]: f for f in indexed_candidates}
            for target_id, (_, _, _, chunk, matched) in reference_candidates.items():
                target = indexed_by_id[target_id]
                connections.append({
                    "connection_type": "file_reference",
                    "label": matched,
                    "explanation": f"This file explicitly references ‘{matched}’ in indexed evidence.",
                    "target_file": self._file_view(target),
                    "source_evidence": [self._chunk_evidence(chunk, source)],
                    "target_evidence": [],
                })

            connections.sort(
                key=lambda item: (item["connection_type"], item["target_file"]["relative_path"] or "", item["label"].casefold())
            )
            return {"source_file": self._file_view(source), "connections": connections}
