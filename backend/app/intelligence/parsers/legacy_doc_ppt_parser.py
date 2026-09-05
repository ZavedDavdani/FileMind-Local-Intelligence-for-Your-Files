"""Safe binary parser for legacy Microsoft Office binary formats (.doc, .ppt, .xls)."""

import os
import re
from typing import List, Optional

from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
)
from app.intelligence.parsers.base import BaseParser, CorruptedDocumentError

LEGACY_PARSER_VERSION = "1.0.0"


def extract_binary_text_streams(file_path: str) -> List[str]:
    """
    Safely extracts readable Unicode (UTF-16-LE) and ASCII text runs from OLE2 binary files
    without loading arbitrary binary macros or untrusted executables.
    """
    with open(file_path, "rb") as f:
        data = f.read()

    # Match UTF-16LE strings (min length 4 characters)
    utf16_pattern = re.compile(b"(?:[\x20-\x7E]\x00){4,}")
    # Match printable ASCII runs (min length 4 characters)
    ascii_pattern = re.compile(b"[\x20-\x7E\t\n\r]{4,}")

    text_runs = []

    # 1. Extract UTF-16 strings
    for m in utf16_pattern.finditer(data):
        try:
            s = m.group(0).decode("utf-16le", errors="ignore").strip()
            if s and len(s) >= 4 and not all(c in " _-+=*#" for c in s):
                text_runs.append(s)
        except Exception:
            pass

    # 2. Extract ASCII strings
    for m in ascii_pattern.finditer(data):
        try:
            s = m.group(0).decode("latin-1", errors="ignore").strip()
            if s and len(s) >= 4 and not all(c in " _-+=*#" for c in s):
                text_runs.append(s)
        except Exception:
            pass

    # Deduplicate adjacent identical runs
    deduped = []
    seen = set()
    for r in text_runs:
        if r not in seen and len(r) > 2:
            seen.add(r)
            deduped.append(r)

    return deduped


class LegacyOfficeParser(BaseParser):
    """Parser for legacy binary Microsoft Office files (.doc, .ppt, .xls)."""

    @property
    def parser_name(self) -> str:
        return "legacy-office-parser"

    @property
    def parser_version(self) -> str:
        return LEGACY_PARSER_VERSION

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "application/msword",
            "application/vnd.ms-powerpoint",
            "application/vnd.ms-excel",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".doc", ".ppt", ".xls"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "application/msword") -> Document:
        file_path = str(file_path)
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

        doc_obj = Document(
            file_id=file_id,
            source_path=file_path,
            filename=filename,
            mime_type=mime_type,
            title=filename,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            total_pages=1,
        )

        try:
            runs = extract_binary_text_streams(file_path)
            if not runs:
                runs = [f"Legacy {ext.upper()} document: {filename} (No plain text streams extracted)."]

            elem_idx = 0
            # Header element
            elem_idx += 1
            doc_obj.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_{elem_idx}",
                    element_type=ElementType.HEADING,
                    text=f"Document: {filename} ({ext.upper()})",
                    level=1,
                    media_type="document",
                    extraction_method="native",
                )
            )

            for r in runs:
                elem_idx += 1
                doc_obj.elements.append(
                    DocumentElement(
                        element_id=f"{file_id}_elem_{elem_idx}",
                        element_type=ElementType.PARAGRAPH,
                        text=r,
                        media_type="document",
                        extraction_method="native",
                    )
                )

        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to extract text from legacy {ext} file {filename}: {str(exc)}") from exc

        return doc_obj
