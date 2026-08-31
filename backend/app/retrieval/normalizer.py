"""Deterministic query normalization and token hygiene for Phase 3 retrieval.

Preserves:
- Case normalization (NFKC lowercase)
- Whitespace stripping and collapsing
- Technical identifiers (e.g. SHA-256, v1.0.0, sqlite-vec, file_events, H1/H2)
- Quoted exact phrases ("...")
- Safe formatting for SQLite FTS5 queries without syntax errors
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NormalizedQuery:
    raw_query: str
    normalized_query: str
    tokens: List[str] = field(default_factory=list)
    phrases: List[str] = field(default_factory=list)
    fts5_query: str = ""
    is_empty: bool = False


# Regex patterns
_PHRASE_REGEX = re.compile(r'"([^"]+)"')
_WHITESPACE_REGEX = re.compile(r"\s+")
# Identifiers allowed characters (alphanumeric, underscore, hyphen, dot, colon, slash)
_TOKEN_SPLIT_REGEX = re.compile(r'[^\w\-\.:/]+')
_SUBTOKEN_SPLIT_REGEX = re.compile(r'[\s_\-\./\\:,;]+')
# FTS5 special operators that should be quoted if appearing as standalone terms
_FTS5_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}


def normalize_query(raw_query: Optional[str]) -> NormalizedQuery:
    """
    Normalizes a user query deterministically.
    
    Returns NormalizedQuery containing:
    - raw_query: verbatim input
    - normalized_query: cleaned string suitable for semantic embedding
    - tokens: list of significant token terms
    - phrases: list of exact quoted phrases extracted
    - fts5_query: safe query formatted for SQLite FTS5 MATCH expressions
    - is_empty: boolean flag if query contains no searchable characters
    """
    if raw_query is None:
        return NormalizedQuery(raw_query="", normalized_query="", is_empty=True)

    # 1. Unicode normalization (NFKC)
    cleaned = unicodedata.normalize("NFKC", raw_query).strip()
    if not cleaned:
        return NormalizedQuery(raw_query=raw_query, normalized_query="", is_empty=True)

    # 2. Extract quoted phrases before removing punctuation
    raw_phrases = _PHRASE_REGEX.findall(cleaned)
    phrases = [p.strip() for p in raw_phrases if p.strip()]

    # 3. Create cleaned text for embedding / dense search
    # Replace quotes and collapse spaces
    dense_text = _PHRASE_REGEX.sub(r" \1 ", cleaned)
    dense_text = _WHITESPACE_REGEX.sub(" ", dense_text).strip()

    # 4. Extract tokens for lexical search
    # Split by non-identifier characters while preserving hyphens, underscores, dots
    token_candidates = _TOKEN_SPLIT_REGEX.split(dense_text)
    tokens = []
    seen = set()
    for tok in token_candidates:
        t = tok.strip("._-/: ")
        if t and len(t) >= 1:
            tokens.append(t)
            seen.add(t.lower())

    if not tokens and not phrases:
        return NormalizedQuery(
            raw_query=raw_query,
            normalized_query="",
            tokens=[],
            phrases=[],
            fts5_query="",
            is_empty=True,
        )

    # 5. Build safe SQLite FTS5 query string
    # Format exact phrases as "phrase" and terms as term* for prefix support
    fts_parts = []

    for phrase in phrases:
        # Sanitize phrase for FTS5
        clean_p = phrase.replace('"', '""').strip()
        if clean_p:
            fts_parts.append(f'"{clean_p}"')

    # Remove terms already covered by phrases if pure exact match
    remaining_text = _PHRASE_REGEX.sub("", cleaned)
    rem_tokens = _TOKEN_SPLIT_REGEX.split(remaining_text)
    
    for tok in rem_tokens:
        t = tok.strip("._-/: ")
        if not t:
            continue
        # If term is an FTS5 reserved keyword, quote it
        if t.upper() in _FTS5_KEYWORDS:
            fts_parts.append(f'"{t}"')
        else:
            # Escape internal double quotes
            safe_t = t.replace('"', '""')
            subparts = [s.replace('"', '""') for s in _SUBTOKEN_SPLIT_REGEX.split(t) if s.strip()]
            # If the token contains multiple sub-parts (e.g. sample.txt or FILEMIND_PRACTICAL),
            # support both composite prefix matching and constituent sub-tokens in FTS5
            if len(subparts) > 1:
                sub_expr = " ".join(f'"{s}"*' if len(s) >= 2 else f'"{s}"' for s in subparts)
                fts_parts.append(f'("{safe_t}"* OR ({sub_expr}))')
            elif len(safe_t) >= 2 and not safe_t.endswith("*"):
                fts_parts.append(f'"{safe_t}"*')
            else:
                fts_parts.append(f'"{safe_t}"')

    fts5_query = " ".join(fts_parts) if fts_parts else ""

    return NormalizedQuery(
        raw_query=raw_query,
        normalized_query=dense_text,
        tokens=tokens,
        phrases=phrases,
        fts5_query=fts5_query,
        is_empty=False,
    )
