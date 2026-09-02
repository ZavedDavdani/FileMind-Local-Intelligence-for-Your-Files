"""Deterministic Chunk Identity Strategy for FileMind."""

import hashlib
import json
from typing import Optional


def compute_chunk_content_hash(canonical_text: str) -> str:
    """Computes a deterministic SHA-256 hash over canonical chunk text."""
    normalized = canonical_text.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def generate_chunk_id(
    file_id: str,
    h1_parent: Optional[str],
    h2_parent: Optional[str],
    chunk_index: int,
    content_hash: str,
) -> str:
    """
    Generates a deterministic, collision-resistant chunk identifier.

    Formula:
    chunk_id = sha256(canonical_json([file_id, h1, h2, chunk_index, content_hash]))[:16]

    Properties:
    1. Deterministic: Reprocessing the exact same document produces identical chunk_ids.
    2. Collision-resistant: 64-bit truncated cryptographic digest (16 hex chars) scoped to
       canonical array representation of file_id, structural heading context, sequence index,
       and content hash.
    3. Change-sensitive: Content edits, index shifts, or heading movements produce a distinct new chunk_id.
    4. Delimiter-safe: Canonical JSON array serialization prevents ambiguous delimiter collisions
       when heading texts contain colons or special characters.
    """
    canonical_key = json.dumps(
        [file_id, h1_parent or "", h2_parent or "", chunk_index, content_hash],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()
    return f"chk_{digest[:16]}"
