"""
FileMind Phase 5.2 — Citation Extraction and Grounding Validation.

Extracts referenced evidence identifiers ([E1], [E2], ...) from model responses,
validates them against the active citation map, and detects unresolved or fabricated citations.
"""

from dataclasses import dataclass, field
import re
from typing import Dict, List, Set, Tuple

from app.ai.prompt import CitationSource


CITATION_PATTERN = re.compile(r"\[[Ee]\s*(\d+)\]")


@dataclass
class CitationValidationResult:
    """Detailed outcome of citation extraction and provenance resolution."""
    valid_citations: List[CitationSource]
    unresolved_citation_ids: List[str]
    has_citations: bool
    is_valid: bool

    def to_dict(self):
        return {
            "valid_citations": [c.to_dict() for c in self.valid_citations],
            "unresolved_citation_ids": self.unresolved_citation_ids,
            "has_citations": self.has_citations,
            "is_valid": self.is_valid,
        }


class CitationValidator:
    """
    Validates model output citations against the deterministic prompt citation map.
    """

    @classmethod
    def extract_and_validate(
        cls,
        answer_text: str,
        citation_map: Dict[str, CitationSource],
    ) -> CitationValidationResult:
        """
        Extracts all `[E{n}]` markers from answer text, resolves valid citations in order of appearance,
        and records any unresolved/hallucinated citation keys.
        """
        if not answer_text or not isinstance(answer_text, str):
            return CitationValidationResult(
                valid_citations=[],
                unresolved_citation_ids=[],
                has_citations=False,
                is_valid=False,
            )

        matches = CITATION_PATTERN.findall(answer_text)
        seen_keys: Set[str] = set()
        valid_citations: List[CitationSource] = []
        unresolved_citation_ids: List[str] = []

        for match_num in matches:
            # Check both normalized integer key (e.g. '01' -> 'E1') and verbatim key
            try:
                norm_key = f"E{int(match_num)}"
            except ValueError:
                norm_key = f"E{match_num}"

            verbatim_key = f"E{match_num}"

            # Determine canonical citation key
            if norm_key in citation_map:
                resolved_key = norm_key
            elif verbatim_key in citation_map:
                resolved_key = verbatim_key
            else:
                resolved_key = None

            dedup_key = resolved_key or verbatim_key
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            if resolved_key:
                valid_citations.append(citation_map[resolved_key])
            else:
                unresolved_citation_ids.append(verbatim_key)

        has_citations = len(valid_citations) > 0
        is_valid = len(unresolved_citation_ids) == 0

        return CitationValidationResult(
            valid_citations=valid_citations,
            unresolved_citation_ids=unresolved_citation_ids,
            has_citations=has_citations,
            is_valid=is_valid,
        )
