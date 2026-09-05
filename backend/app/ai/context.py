"""
FileMind Phase 5.1 — Context Assembly and Token Budget Foundation.

Sits between retrieval (SearchResultItem / ChunkItem) and future local LLM generation.
Guarantees deterministic token budgeting, non-negative accounting, exact provenance preservation,
and protection against unbounded context-window overflow.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Union


class EvidenceStatus(str, Enum):
    """Reflects the overall outcome of context assembly."""
    READY = "READY"                      # Bounded evidence successfully assembled
    NO_EVIDENCE = "NO_EVIDENCE"          # Candidate list was empty or contained no parseable content
    BUDGET_LIMITED = "BUDGET_LIMITED"    # Candidates existed, but budget constraints prevented inclusion


class OmissionReason(str, Enum):
    """Diagnostic reason why a retrieved candidate was excluded from the bounded context."""
    BUDGET_EXCEEDED = "budget_exceeded"
    OVERSIZED_SINGLE_CHUNK = "oversized_single_chunk"
    DUPLICATE_CHUNK = "duplicate_chunk"
    INVALID_EMPTY_CONTENT = "invalid_empty_content"
    MAX_CHUNKS_REACHED = "max_chunks_reached"


class TokenEstimator:
    """
    Deterministic token estimator for heuristic budget calculation.

    Design & Accuracy Contract:
    - This is a conservative heuristic estimator, NOT a full model BPE/WordPiece tokenizer.
    - CJK characters (0x4E00..0x9FFF, etc.) are estimated at 1 token per character.
    - Non-CJK latin text is conservatively estimated at ~3.5 characters per token (ceil(len / 3.5))
      to deliberately err on the side of safety and avoid context overflow.
    - Returns 0 for empty or whitespace-only text.
    - Returns >= 1 for any non-empty string.
    """

    def __init__(self, chars_per_token_non_cjk: float = 3.5):
        self.chars_per_token_non_cjk = max(1.0, chars_per_token_non_cjk)

    def estimate(self, text: Optional[str]) -> int:
        if not text:
            return 0
        cleaned = text.strip()
        if not cleaned:
            return 0

        # Fast path for standard ASCII text
        if cleaned.isascii():
            return max(1, math.ceil(len(cleaned) / self.chars_per_token_non_cjk))

        cjk_count = 0
        non_cjk_count = 0
        for char in cleaned:
            cp = ord(char)
            if (
                0x4E00 <= cp <= 0x9FFF
                or 0x3400 <= cp <= 0x4DBF
                or 0x3040 <= cp <= 0x309F
                or 0x30A0 <= cp <= 0x30FF
                or 0xAC00 <= cp <= 0xD7AF
            ):
                cjk_count += 1
            else:
                non_cjk_count += 1

        non_cjk_tokens = math.ceil(non_cjk_count / self.chars_per_token_non_cjk)
        return max(1, cjk_count + non_cjk_tokens)

    def estimate_framing_overhead(self, source_file: str, section: Optional[str] = None, page: Optional[int] = None) -> int:
        """Estimates token overhead of citation header markers (e.g. `[Document: report.pdf | Page: 2]`)."""
        header_sample = f"[Document: {source_file}"
        if section:
            header_sample += f" | Section: {section}"
        if page is not None:
            header_sample += f" | Page: {page}"
        header_sample += "]\n\n"
        return self.estimate(header_sample)


@dataclass(frozen=True)
class ContextBudgetConfig:
    """
    Explicit token budget model defining context allocations.

    Defaults are conservatively tuned for standard local 4B/7B models (e.g. Qwen 2.5 / Llama 3 4K-8K windows):
    - max_context_tokens: 4096 total window
    - reserved_system_tokens: 500 for system prompt and formatting instructions
    - reserved_output_tokens: 1000 for generation headroom
    - evidence_budget: remaining 2596 tokens dedicated to retrieved document chunks
    """
    max_context_tokens: int = 4096
    reserved_system_tokens: int = 500
    reserved_output_tokens: int = 1000
    max_chunks: int = 20

    def __post_init__(self):
        if self.max_context_tokens < 0:
            raise ValueError("max_context_tokens cannot be negative")
        if self.reserved_system_tokens < 0:
            raise ValueError("reserved_system_tokens cannot be negative")
        if self.reserved_output_tokens < 0:
            raise ValueError("reserved_output_tokens cannot be negative")
        if self.max_chunks < 0:
            raise ValueError("max_chunks cannot be negative")

    @classmethod
    def for_model(cls, model_name: Optional[str] = None) -> "ContextBudgetConfig":
        """
        Dynamically adjusts context limits based on the model identity.
        Models with larger context windows (e.g. 8k, 16k, 32k, 128k) receive expanded
        evidence budgets while preserving system & output headroom.
        """
        if not model_name:
            return cls()
        m_lower = model_name.lower()
        if any(tag in m_lower for tag in ("32k", "128k", "qwen2.5", "qwen:7b", "qwen:14b", "qwen:32b")):
            return cls(
                max_context_tokens=8192,
                reserved_system_tokens=800,
                reserved_output_tokens=1500,
                max_chunks=30,
            )
        elif any(tag in m_lower for tag in ("8k", "llama3", "mistral")):
            return cls(
                max_context_tokens=8192,
                reserved_system_tokens=600,
                reserved_output_tokens=1200,
                max_chunks=25,
            )
        elif any(tag in m_lower for tag in ("2k", "tiny", "phi")):
            return cls(
                max_context_tokens=2048,
                reserved_system_tokens=400,
                reserved_output_tokens=600,
                max_chunks=10,
            )
        return cls()

    @property
    def evidence_budget(self) -> int:
        """Available budget strictly allocated for retrieved evidence."""
        return max(0, self.max_context_tokens - self.reserved_system_tokens - self.reserved_output_tokens)


@dataclass
class ContextItem:
    """Structured evidence item with complete provenance preserved for citation grounding."""
    chunk_id: str
    file_id: str
    source_file: str
    source_path: str
    content: str
    estimated_tokens: int
    page: Optional[int] = None
    section: Optional[str] = None
    h1_parent: Optional[str] = None
    h2_parent: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    frame_index: Optional[int] = None
    media_type: str = "document"
    extraction_method: Optional[str] = None
    content_hash: Optional[str] = None
    score: Optional[float] = None
    reranker_score: Optional[float] = None
    rrf_score: Optional[float] = None
    lexical_score: Optional[float] = None
    dense_score: Optional[float] = None
    retrieval_method: Optional[str] = None
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    chunker_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def format_grounded_block(self) -> str:
        """Formats evidence block with provenance header for future LLM prompt insertion."""
        header_parts = [f"Source: {self.source_file}"]
        if self.section and self.section != "General":
            header_parts.append(f"Section: {self.section}")
        if self.page is not None:
            header_parts.append(f"Page: {self.page}")
        if self.sheet_name:
            header_parts.append(f"Sheet: {self.sheet_name}")
        if self.slide_number is not None:
            header_parts.append(f"Slide: {self.slide_number}")
        if self.time_start is not None and self.time_end is not None:
            def _fmt_time(s: float) -> str:
                m = int(s // 60)
                sec = int(s % 60)
                return f"{m:02d}:{sec:02d}"
            header_parts.append(f"Timestamp: [{_fmt_time(self.time_start)} - {_fmt_time(self.time_end)}]")
        elif self.time_start is not None:
            m = int(self.time_start // 60)
            sec = int(self.time_start % 60)
            header_parts.append(f"Timestamp: {m:02d}:{sec:02d}")
        if self.frame_index is not None:
            header_parts.append(f"Keyframe: #{self.frame_index}")
        if self.line_start is not None and self.line_end is not None:
            header_parts.append(f"Lines: {self.line_start}-{self.line_end}")
        if self.media_type and self.media_type != "document":
            header_parts.append(f"Media: {self.media_type.upper()}")
        if self.extraction_method:
            header_parts.append(f"Method: {self.extraction_method}")

        header = " | ".join(header_parts)
        return f"[{header}]\n{self.content.strip()}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_id": self.file_id,
            "source_file": self.source_file,
            "source_path": self.source_path,
            "page": self.page,
            "section": self.section,
            "h1_parent": self.h1_parent,
            "h2_parent": self.h2_parent,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "sheet_name": self.sheet_name,
            "slide_number": self.slide_number,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "frame_index": self.frame_index,
            "media_type": self.media_type,
            "extraction_method": self.extraction_method,
            "content": self.content,
            "content_hash": self.content_hash,
            "score": self.score,
            "reranker_score": self.reranker_score,
            "rrf_score": self.rrf_score,
            "lexical_score": self.lexical_score,
            "dense_score": self.dense_score,
            "retrieval_method": self.retrieval_method,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "chunker_version": self.chunker_version,
            "estimated_tokens": self.estimated_tokens,
            "metadata": self.metadata,
        }


@dataclass
class OmittedCandidate:
    """Record of a candidate omitted during context assembly and its reason."""
    chunk_id: str
    file_id: Optional[str]
    source_file: Optional[str]
    estimated_tokens: int
    reason: OmissionReason
    details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_id": self.file_id,
            "source_file": self.source_file,
            "estimated_tokens": self.estimated_tokens,
            "reason": self.reason.value,
            "details": self.details,
        }


@dataclass
class BudgetAccounting:
    """Inspectable telemetry detailing token and candidate allocations."""
    total_budget: int
    system_reserved: int
    output_reserved: int
    evidence_budget: int
    evidence_used: int
    evidence_remaining: int
    candidates_considered: int
    candidates_included: int
    candidates_omitted: int
    omitted_candidates: List[OmittedCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_budget": self.total_budget,
            "system_reserved": self.system_reserved,
            "output_reserved": self.output_reserved,
            "evidence_budget": self.evidence_budget,
            "evidence_used": self.evidence_used,
            "evidence_remaining": self.evidence_remaining,
            "candidates_considered": self.candidates_considered,
            "candidates_included": self.candidates_included,
            "candidates_omitted": self.candidates_omitted,
            "omitted_candidates": [o.to_dict() for o in self.omitted_candidates],
        }


@dataclass
class BoundedContextPackage:
    """The complete bounded context package ready for downstream local RAG consumption."""
    status: EvidenceStatus
    items: List[ContextItem]
    budget: BudgetAccounting

    def to_context_blocks(self) -> List[str]:
        """Returns ordered list of formatted evidence blocks."""
        return [item.format_grounded_block() for item in self.items]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "items": [item.to_dict() for item in self.items],
            "budget": self.budget.to_dict(),
        }


class ContextBuilder:
    """
    Deterministic context builder enforcing token budgets across retrieved evidence.
    """

    def __init__(
        self,
        estimator: Optional[TokenEstimator] = None,
        default_budget: Optional[ContextBudgetConfig] = None,
    ):
        self.estimator = estimator or TokenEstimator()
        self.default_budget = default_budget or ContextBudgetConfig()

    def _extract_item(self, cand: Any) -> Optional[ContextItem]:
        """Extracts normalized ContextItem from SearchResultItem, ChunkItem, or dict."""
        if hasattr(cand, "to_dict"):
            d = cand.to_dict()
        elif hasattr(cand, "__dict__"):
            d = cand.__dict__
        elif isinstance(cand, dict):
            d = cand
        else:
            return None

        chunk_id = str(d.get("chunk_id") or "")
        if not chunk_id:
            return None

        file_id = str(d.get("file_id") or "")
        source_file = str(d.get("source_file") or d.get("filename") or "Unknown")
        source_path = str(d.get("source_path") or d.get("path") or source_file)
        content = str(d.get("content") or "")

        if not content.strip():
            return None

        token_est = self.estimator.estimate(content)
        framing_est = self.estimator.estimate_framing_overhead(
            source_file=source_file,
            section=d.get("section"),
            page=d.get("page"),
        )
        total_item_tokens = token_est + framing_est

        meta_dict = dict(d.get("metadata") or {})
        return ContextItem(
            chunk_id=chunk_id,
            file_id=file_id,
            source_file=source_file,
            source_path=source_path,
            content=content,
            estimated_tokens=total_item_tokens,
            page=d.get("page"),
            section=d.get("section"),
            h1_parent=d.get("h1_parent"),
            h2_parent=d.get("h2_parent"),
            line_start=d.get("line_start"),
            line_end=d.get("line_end"),
            char_start=d.get("char_start"),
            char_end=d.get("char_end"),
            sheet_name=d.get("sheet_name") or meta_dict.get("sheet_name"),
            slide_number=d.get("slide_number") if d.get("slide_number") is not None else meta_dict.get("slide_number"),
            time_start=d.get("time_start") if d.get("time_start") is not None else meta_dict.get("time_start"),
            time_end=d.get("time_end") if d.get("time_end") is not None else meta_dict.get("time_end"),
            frame_index=d.get("frame_index") if d.get("frame_index") is not None else meta_dict.get("frame_index"),
            media_type=d.get("media_type") or meta_dict.get("media_type") or "document",
            extraction_method=d.get("extraction_method") or meta_dict.get("extraction_method"),
            content_hash=d.get("content_hash"),
            score=d.get("score"),
            reranker_score=d.get("reranker_score"),
            rrf_score=d.get("rrf_score"),
            lexical_score=d.get("lexical_score"),
            dense_score=d.get("dense_score"),
            retrieval_method=d.get("retrieval_method"),
            parser_name=d.get("parser_name"),
            parser_version=d.get("parser_version"),
            chunker_version=d.get("chunker_version"),
            metadata=meta_dict,
        )

    def build_context(
        self,
        candidates: Sequence[Any],
        budget_config: Optional[ContextBudgetConfig] = None,
    ) -> BoundedContextPackage:
        """
        Assembles a bounded context package from retrieved candidates respecting the budget config.
        """
        cfg = budget_config or self.default_budget
        evidence_budget = cfg.evidence_budget

        if not candidates:
            accounting = BudgetAccounting(
                total_budget=cfg.max_context_tokens,
                system_reserved=cfg.reserved_system_tokens,
                output_reserved=cfg.reserved_output_tokens,
                evidence_budget=evidence_budget,
                evidence_used=0,
                evidence_remaining=evidence_budget,
                candidates_considered=0,
                candidates_included=0,
                candidates_omitted=0,
                omitted_candidates=[],
            )
            return BoundedContextPackage(
                status=EvidenceStatus.NO_EVIDENCE,
                items=[],
                budget=accounting,
            )

        seen_chunk_ids = set()
        included_items: List[ContextItem] = []
        omitted_candidates: List[OmittedCandidate] = []
        evidence_used = 0
        considered_count = 0

        for cand in candidates:
            considered_count += 1
            # Check candidate representation
            raw_chunk_id = None
            if isinstance(cand, dict):
                raw_chunk_id = cand.get("chunk_id")
            elif hasattr(cand, "chunk_id"):
                raw_chunk_id = getattr(cand, "chunk_id")

            if not raw_chunk_id:
                omitted_candidates.append(
                    OmittedCandidate(
                        chunk_id="unknown",
                        file_id=None,
                        source_file=None,
                        estimated_tokens=0,
                        reason=OmissionReason.INVALID_EMPTY_CONTENT,
                        details="Candidate is missing chunk_id",
                    )
                )
                continue

            # Deduplication Check
            if raw_chunk_id in seen_chunk_ids:
                omitted_candidates.append(
                    OmittedCandidate(
                        chunk_id=raw_chunk_id,
                        file_id=getattr(cand, "file_id", None) if not isinstance(cand, dict) else cand.get("file_id"),
                        source_file=getattr(cand, "source_file", None) if not isinstance(cand, dict) else cand.get("source_file"),
                        estimated_tokens=0,
                        reason=OmissionReason.DUPLICATE_CHUNK,
                        details=f"Chunk {raw_chunk_id} already included in context",
                    )
                )
                continue

            item = self._extract_item(cand)
            if item is None:
                omitted_candidates.append(
                    OmittedCandidate(
                        chunk_id=raw_chunk_id,
                        file_id=getattr(cand, "file_id", None) if not isinstance(cand, dict) else cand.get("file_id"),
                        source_file=getattr(cand, "source_file", None) if not isinstance(cand, dict) else cand.get("source_file"),
                        estimated_tokens=0,
                        reason=OmissionReason.INVALID_EMPTY_CONTENT,
                        details="Empty or unparseable candidate content",
                    )
                )
                continue

            # Max Chunks Cap
            if len(included_items) >= cfg.max_chunks:
                omitted_candidates.append(
                    OmittedCandidate(
                        chunk_id=item.chunk_id,
                        file_id=item.file_id,
                        source_file=item.source_file,
                        estimated_tokens=item.estimated_tokens,
                        reason=OmissionReason.MAX_CHUNKS_REACHED,
                        details=f"Maximum chunk limit reached ({cfg.max_chunks})",
                    )
                )
                continue

            item_cost = item.estimated_tokens

            # Check if this chunk alone exceeds the entire evidence budget
            if item_cost > evidence_budget:
                omitted_candidates.append(
                    OmittedCandidate(
                        chunk_id=item.chunk_id,
                        file_id=item.file_id,
                        source_file=item.source_file,
                        estimated_tokens=item_cost,
                        reason=OmissionReason.OVERSIZED_SINGLE_CHUNK,
                        details=f"Chunk cost ({item_cost} tokens) exceeds total evidence budget ({evidence_budget} tokens)",
                    )
                )
                continue

            # Check if adding this chunk exceeds remaining evidence budget
            if evidence_used + item_cost <= evidence_budget:
                seen_chunk_ids.add(item.chunk_id)
                included_items.append(item)
                evidence_used += item_cost
            else:
                omitted_candidates.append(
                    OmittedCandidate(
                        chunk_id=item.chunk_id,
                        file_id=item.file_id,
                        source_file=item.source_file,
                        estimated_tokens=item_cost,
                        reason=OmissionReason.BUDGET_EXCEEDED,
                        details=f"Adding {item_cost} tokens would exceed remaining budget ({evidence_budget - evidence_used} remaining of {evidence_budget})",
                    )
                )

        evidence_remaining = max(0, evidence_budget - evidence_used)

        accounting = BudgetAccounting(
            total_budget=cfg.max_context_tokens,
            system_reserved=cfg.reserved_system_tokens,
            output_reserved=cfg.reserved_output_tokens,
            evidence_budget=evidence_budget,
            evidence_used=evidence_used,
            evidence_remaining=evidence_remaining,
            candidates_considered=considered_count,
            candidates_included=len(included_items),
            candidates_omitted=len(omitted_candidates),
            omitted_candidates=omitted_candidates,
        )

        if len(included_items) > 0:
            status = EvidenceStatus.READY
        elif considered_count > 0 and len(omitted_candidates) > 0:
            status = EvidenceStatus.BUDGET_LIMITED
        else:
            status = EvidenceStatus.NO_EVIDENCE

        return BoundedContextPackage(
            status=status,
            items=included_items,
            budget=accounting,
        )


# Global default context builder instance
default_context_builder = ContextBuilder()
