"""Hierarchical Chunker: Structure-first document chunking with provenance preservation."""

from typing import List, Optional
from app.intelligence.chunker.identity import (
    compute_chunk_content_hash,
    generate_chunk_id,
)
from app.intelligence.chunker.provenance import ChunkProvenance
from app.intelligence.models import Document, DocumentElement, ElementType

CHUNKER_VERSION = "phase2-hierarchical-v1"


class HierarchicalChunker:
    """
    Structure-first chunker that traverses document heading hierarchies,
    preserving semantic sections, table integrity, and precise source provenance.
    """

    def __init__(
        self,
        target_chunk_chars: int = 1500,
        max_chunk_chars: int = 3000,
        overlap_chars: int = 150,
    ):
        self.target_chunk_chars = target_chunk_chars
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars
        self.chunker_version = CHUNKER_VERSION

    def chunk_document(self, doc: Document) -> List[ChunkProvenance]:
        """
        Splits a normalized Document into a sequence of provenance-preserving chunks.
        """
        chunks: List[ChunkProvenance] = []
        chunk_idx = 0

        current_h1: Optional[str] = None
        current_h2: Optional[str] = None
        current_section: Optional[str] = None

        # Element accumulator for building chunks
        accum_elements: List[DocumentElement] = []
        accum_chars = 0

        def flush_accumulator():
            nonlocal chunk_idx, accum_elements, accum_chars
            if not accum_elements:
                return

            chunk_text = "\n\n".join(e.text for e in accum_elements if e.text.strip()).strip()
            if not chunk_text:
                accum_elements = []
                accum_chars = 0
                return

            pages = [e.page_number for e in accum_elements if e.page_number is not None]
            min_page = min(pages) if pages else None

            lines_start = [e.line_start for e in accum_elements if e.line_start is not None]
            lines_end = [e.line_end for e in accum_elements if e.line_end is not None]
            min_line = min(lines_start) if lines_start else None
            max_line = max(lines_end) if lines_end else None

            chars_start = [e.char_start for e in accum_elements if e.char_start is not None]
            chars_end = [e.char_end for e in accum_elements if e.char_end is not None]
            min_char = min(chars_start) if chars_start else None
            max_char = max(chars_end) if chars_end else None

            content_types = {e.element_type for e in accum_elements}
            c_type = "text"
            if ElementType.TABLE in content_types:
                c_type = "table"
            elif ElementType.CODE_BLOCK in content_types:
                c_type = "code"

            content_hash = compute_chunk_content_hash(chunk_text)
            chunk_id = generate_chunk_id(
                file_id=doc.file_id,
                h1_parent=current_h1,
                h2_parent=current_h2,
                chunk_index=chunk_idx,
                content_hash=content_hash,
            )

            # Estimate token count (~4 chars per token)
            token_count = max(1, len(chunk_text) // 4)

            provenance = ChunkProvenance(
                chunk_id=chunk_id,
                file_id=doc.file_id,
                source_file=doc.filename,
                source_path=doc.source_path,
                page=min_page,
                section=current_section or current_h1 or "General",
                h1_parent=current_h1,
                h2_parent=current_h2,
                line_start=min_line,
                line_end=max_line,
                char_start=min_char,
                char_end=max_char,
                content_hash=content_hash,
                chunk_index=chunk_idx,
                parser_name=doc.parser_name,
                parser_version=doc.parser_version,
                chunker_version=self.chunker_version,
                content=chunk_text,
                content_type=c_type,
                token_count=token_count,
                metadata={
                    "element_count": len(accum_elements),
                    "mime_type": doc.mime_type,
                },
            )

            chunks.append(provenance)
            chunk_idx += 1
            accum_elements = []
            accum_chars = 0

        for elem in doc.elements:
            elem_len = len(elem.text)

            if elem.element_type == ElementType.HEADING:
                # Heading marks a strong structural boundary.
                # If accumulator only contains a previous heading (no body text), don't create an isolated 1-line chunk.
                has_body_content = any(e.element_type != ElementType.HEADING for e in accum_elements)
                if has_body_content:
                    flush_accumulator()
                else:
                    accum_elements = []
                    accum_chars = 0

                if elem.level == 1:
                    current_h1 = elem.text.strip()
                    current_h2 = None
                    current_section = current_h1
                elif elem.level == 2:
                    current_h2 = elem.text.strip()
                    current_section = f"{current_h1} > {current_h2}" if current_h1 else current_h2
                else:
                    current_section = f"{current_h1} > {elem.text.strip()}" if current_h1 else elem.text.strip()

                accum_elements.append(elem)
                accum_chars += elem_len
                continue

            if elem.element_type == ElementType.TABLE:
                # Table preservation: Flush previous text, keep table intact
                flush_accumulator()
                accum_elements.append(elem)
                flush_accumulator()
                continue

            # Check if adding this element would exceed max chunk size
            if accum_chars + elem_len > self.max_chunk_chars and accum_elements:
                flush_accumulator()

            accum_elements.append(elem)
            accum_chars += elem_len

            # Check if target size is reached
            if accum_chars >= self.target_chunk_chars:
                flush_accumulator()

        flush_accumulator()
        return chunks
