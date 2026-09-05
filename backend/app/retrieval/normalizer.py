"""Deterministic query normalization and token hygiene for retrieval.

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


def is_cjk_char(c: str) -> bool:
    """Returns True if the character is in a CJK, Hiragana, Katakana, or Hangul Unicode block."""
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0x3040 <= cp <= 0x309F
        or 0x30A0 <= cp <= 0x30FF
        or 0xAC00 <= cp <= 0xD7AF
    )


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

    # 2. Extract quoted phrases before removing punctuation (deduplicated in order)
    raw_phrases = _PHRASE_REGEX.findall(cleaned)
    phrases = []
    seen_phrases = set()
    for p in raw_phrases:
        p_clean = p.strip()
        if p_clean:
            p_lower = p_clean.lower()
            if p_lower not in seen_phrases:
                seen_phrases.add(p_lower)
                phrases.append(p_clean)

    # 3. Create cleaned text for embedding / dense search
    # Replace quotes and collapse spaces
    dense_text = _PHRASE_REGEX.sub(r" \1 ", cleaned)
    dense_text = _WHITESPACE_REGEX.sub(" ", dense_text).strip()

    # 4. Extract tokens for lexical search (deduplicated in first-seen order)
    # Split by non-identifier characters while preserving hyphens, underscores, dots
    token_candidates = _TOKEN_SPLIT_REGEX.split(dense_text)
    tokens = []
    seen_tokens = set()
    for tok in token_candidates:
        t = tok.strip("._-/: ")
        if t and len(t) >= 1:
            t_lower = t.lower()
            if t_lower not in seen_tokens:
                seen_tokens.add(t_lower)
                tokens.append(t)

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
    seen_fts_tokens = set()

    for tok in rem_tokens:
        t = tok.strip("._-/: ")
        if not t:
            continue
        t_lower = t.lower()
        if t_lower in seen_fts_tokens:
            continue
        seen_fts_tokens.add(t_lower)

        # If term is an FTS5 reserved keyword, quote it
        if t.upper() in _FTS5_KEYWORDS:
            fts_parts.append(f'"{t}"')
        else:
            # Escape internal double quotes
            safe_t = t.replace('"', '""')
            is_cjk = any(is_cjk_char(c) for c in t)
            subparts = [s.replace('"', '""') for s in _SUBTOKEN_SPLIT_REGEX.split(t) if s.strip()]
            # If the token contains multiple sub-parts (e.g. sample.txt or FILEMIND_PRACTICAL),
            # support both composite matching and constituent sub-tokens in FTS5
            if len(subparts) > 1:
                fts_parts.append(f'"{safe_t}"')
                for sub in subparts:
                    if len(sub) >= 2 and sub.lower() not in seen_fts_tokens and sub.upper() not in _FTS5_KEYWORDS:
                        fts_parts.append(f'"{sub}"*')
            elif (len(safe_t) >= 2 or is_cjk) and not safe_t.endswith("*"):
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
