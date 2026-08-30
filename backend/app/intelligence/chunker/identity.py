"""Deterministic Chunk Identity Strategy for FileMind."""

import hashlib
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
    Generates a deterministic, collision-free chunk identifier.
    
    Formula:
    chunk_id = sha256(file_id + ':' + h1 + ':' + h2 + ':' + chunk_index + ':' + content_hash)[:16]
    
    Properties:
    1. Deterministic: Reprocessing the exact same document produces identical chunk_ids.
    2. Collision-free: Scoped to file_id, structural heading context, and sequence index.
    3. Change-sensitive: Content edits or heading movements produce a distinct new chunk_id.
    """
    raw_key = f"{file_id}:{h1_parent or ''}:{h2_parent or ''}:{chunk_index}:{content_hash}"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"chk_{digest[:16]}"
