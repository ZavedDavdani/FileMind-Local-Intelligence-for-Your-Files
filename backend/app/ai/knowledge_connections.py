"""Dynamic, source-backed knowledge connections for Phase 5.5 Batch 3.2.

Connections are intentionally not persisted: every response is reconstructed
from the current file records, chunks, and valid Document Insight cache.
"""

import re
from typing import Any, Dict, List, Set

from app.db.connection import DatabaseManager
from app.db.repository import Repository
from app.ai.document_understanding import DocumentUnderstandingService
from app.core.config import OLLAMA_MODEL


def _topic_key(topic: str) -> str:
    return " ".join(str(topic).casefold().split())


class KnowledgeConnectionService:
    """Builds explainable shared-topic and exact file-reference links."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    @staticmethod
    def _citation_is_current(repo: Repository, citation: Dict[str, Any], file_rec: Dict[str, Any]) -> bool:
        chunk_id = citation.get("chunk_id")
        if not chunk_id:
            return False
        chunk = repo.get_chunk_by_id(chunk_id)
        return bool(
            chunk
            and chunk.get("file_id") == file_rec.get("file_id")
            and citation.get("content_hash") == chunk.get("content_hash")
        )

    def _current_topic_insight(self, repo: Repository, file_rec: Dict[str, Any]) -> Dict[str, Any] | None:
        insight = repo.get_document_insight(file_rec["file_id"], model_name=OLLAMA_MODEL)
        chunks = repo.get_chunks_by_file(file_rec["file_id"])
        if not insight or not DocumentUnderstandingService.is_cached_insight_current(
            file_rec, chunks, insight, OLLAMA_MODEL
        ):
            return None
        citations = [
            citation for citation in insight.get("citations") or []
            if self._citation_is_current(repo, citation, file_rec)
        ]
        # Topics are generated derived knowledge; do not expose them as a
        # connection unless their insight still has resolvable evidence.
        if not citations:
            return None
        return {"topics": insight.get("key_topics") or [], "citations": citations}

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
        return bool(re.search(r"(?<![\\w./-])" + escaped + r"(?![\\w./-])", content.replace("\\", "/"), re.I))

    def get_connections(self, file_id: str) -> Dict[str, Any]:
        with self.db.session() as conn:
            repo = Repository(conn)
            source = repo.get_file_by_id(file_id)
            if not source:
                raise ValueError(f"File with ID {file_id} not found")
            if source.get("index_status") != "INDEXED":
                return {"source_file": self._file_view(source), "connections": []}

            indexed = [f for f in repo.list_files(status="INDEXED", limit=100000) if f["file_id"] != file_id]
            connections: List[Dict[str, Any]] = []
            seen: Set[tuple[str, str, str]] = set()

            source_insight = self._current_topic_insight(repo, source)
            if source_insight:
                source_topics = {_topic_key(t): str(t).strip() for t in source_insight["topics"] if _topic_key(t)}
                for target in indexed:
                    target_insight = self._current_topic_insight(repo, target)
                    if not target_insight:
                        continue
                    target_topics = {_topic_key(t) for t in target_insight["topics"] if _topic_key(t)}
                    for key in sorted(set(source_topics) & target_topics):
                        dedup = ("shared_topic", target["file_id"], key)
                        if dedup in seen:
                            continue
                        seen.add(dedup)
                        connections.append({
                            "connection_type": "shared_topic",
                            "label": source_topics[key],
                            "explanation": f"Both files have the current grounded topic ‘{source_topics[key]}’.",
                            "target_file": self._file_view(target),
                            "source_evidence": source_insight["citations"],
                            "target_evidence": target_insight["citations"],
                        })

            reference_candidates: Dict[str, tuple[int, int, str, Dict[str, Any], str]] = {}
            for chunk in repo.get_chunks_by_file(file_id):
                content = chunk.get("content") or ""
                for target in indexed:
                    relative = (target.get("relative_path") or "").replace("\\", "/")
                    filename = target.get("filename") or ""
                    references = [relative] if relative else []
                    # A basename is only safe when it uniquely identifies one indexed file.
                    if filename and sum(f.get("filename", "").casefold() == filename.casefold() for f in indexed + [source]) == 1:
                        references.append(filename)
                    matched = next((r for r in references if self._contains_exact_reference(content, r)), None)
                    if not matched:
                        continue
                    # Prefer a relative-path match over a basename, then use
                    # stable chunk order/identity to retain one useful proof.
                    rank = 0 if matched == relative else 1
                    candidate = (rank, int(chunk.get("chunk_index") or 0), chunk["chunk_id"], chunk, matched)
                    existing = reference_candidates.get(target["file_id"])
                    if existing is None or candidate[:3] < existing[:3]:
                        reference_candidates[target["file_id"]] = candidate

            indexed_by_id = {f["file_id"]: f for f in indexed}
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

            connections.sort(key=lambda item: (item["connection_type"], item["target_file"]["relative_path"] or "", item["label"].casefold()))
            return {"source_file": self._file_view(source), "connections": connections}
