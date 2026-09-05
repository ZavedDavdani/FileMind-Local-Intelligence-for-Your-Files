"""
FileMind Citation Extraction and Grounding Validation.

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
        require_citations: bool = False,
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

        # Build normalized lookup map from citation_map for collision-free case- and padding-insensitive lookup
        norm_map: Dict[str, CitationSource] = {}
        for k, v in (citation_map or {}).items():
            norm_map[k] = v
            norm_map[k.upper()] = v
            norm_map[k.lower()] = v
            m = re.match(r"^[Ee]\s*(\d+)$", str(k).strip())
            if m:
                norm_map[f"E{int(m.group(1))}"] = v
                norm_map[f"e{int(m.group(1))}"] = v

        matches = CITATION_PATTERN.findall(answer_text)
        seen_keys: Set[str] = set()
        valid_citations: List[CitationSource] = []
        unresolved_citation_ids: List[str] = []

        for match_num in matches:
            try:
                norm_key = f"E{int(match_num)}"
            except ValueError:
                norm_key = f"E{match_num}"

            verbatim_key = f"E{match_num}"

            # Determine canonical citation key from normalized map
            resolved_source = norm_map.get(norm_key) or norm_map.get(verbatim_key) or norm_map.get(verbatim_key.upper())

            dedup_key = norm_key if resolved_source else verbatim_key
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            if resolved_source:
                valid_citations.append(resolved_source)
            else:
                unresolved_citation_ids.append(verbatim_key)

        has_citations = len(valid_citations) > 0
        is_valid = len(unresolved_citation_ids) == 0 and (has_citations or not require_citations)

        return CitationValidationResult(
            valid_citations=valid_citations,
            unresolved_citation_ids=unresolved_citation_ids,
            has_citations=has_citations,
            is_valid=is_valid,
        )
