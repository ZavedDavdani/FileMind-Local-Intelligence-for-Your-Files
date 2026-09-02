"""Deterministic corpus text and byte decoding utility.

Integrity & Corpus Quality Invariant:
Never silently replace undecodable byte sequences with Unicode replacement characters (U+FFFD).
Byte decoding must be strict and explicit. Undecodable bytes raise CorruptedDocumentError,
preventing silent evidence corruption in downstream retrieval and RAG layers.
"""

import os
from typing import Optional

from app.intelligence.parsers.base import CorruptedDocumentError


def read_text_file_strictly(file_path: str, filename: Optional[str] = None) -> str:
    """
    Reads a text file from disk with strict UTF-8 (and UTF-8-BOM) decoding.

    Args:
        file_path: Absolute path to the file.
        filename: Optional display filename for error diagnostics.

    Returns:
        Decoded string.

    Raises:
        CorruptedDocumentError: If the file contains invalid/undecodable byte sequences
                                or cannot be read.
    """
    display_name = filename or os.path.basename(file_path)
    try:
        with open(file_path, "rb") as f:
            raw_bytes = f.read()
    except Exception as exc:
        raise CorruptedDocumentError(f"Failed to read file '{display_name}': {str(exc)}") from exc

    return decode_bytes_strictly(raw_bytes, display_name)


def decode_bytes_strictly(raw_bytes: bytes, filename: str = "document") -> str:
    """
    Strictly decodes raw byte content into a Unicode string.

    Tries standard UTF-8 with BOM support (utf-8-sig).
    If decoding fails, raises CorruptedDocumentError with byte offset and diagnostic details.

    Never uses errors='replace' or errors='ignore'.
    """
    if not raw_bytes:
        return ""

    try:
        # utf-8-sig transparently strips BOM if present and decodes UTF-8 strictly
        return raw_bytes.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise CorruptedDocumentError(
            f"Corrupted or invalid character encoding in '{filename}' at byte offset {exc.start}: "
            f"invalid UTF-8 byte sequence ({exc.reason}). "
            "Corpus integrity policy rejects silent replacement."
        ) from exc
