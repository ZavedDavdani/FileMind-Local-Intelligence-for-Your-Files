"""Hierarchical Chunker: Structure-first document chunking with provenance preservation."""

from typing import List, Optional
from app.intelligence.chunker.identity import (
    compute_chunk_content_hash,
    generate_chunk_id,
)
from app.intelligence.chunker.provenance import ChunkProvenance
from app.intelligence.models import Document, DocumentElement, ElementType

CHUNKER_VERSION = "phase2-hierarchical-v2"



def estimate_token_count(text: str) -> int:
    """
    Computes an approximate token count for heuristic budget planning.

    Semantic Contract:
    - This is an approximate planning metric (characters/ideographs heuristic), NOT an exact model tokenizer count.
    - Returns 0 for empty or whitespace-only strings.
    - For non-empty strings, minimum estimated token count is 1.
    - CJK characters (Chinese, Japanese Kanji/Kana, Korean Hangul) are estimated at 1 token per character.
    - Non-CJK text is estimated at ~4 characters per token (len // 4).
    """
    cleaned = text.strip()
    if not cleaned:
        return 0

    cjk_count = 0
    non_cjk_chars = 0
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
            non_cjk_chars += 1

    estimated = cjk_count + (non_cjk_chars // 4)
    return max(1, estimated)


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
        Supports deterministic character-based element overlap between chunks within
        the same semantic section.
        """
        chunks: List[ChunkProvenance] = []
        chunk_idx = 0

        current_h1: Optional[str] = None
        current_h2: Optional[str] = None
        current_section: Optional[str] = None

        # Element accumulator for building chunks
        accum_elements: List[DocumentElement] = []
        accum_chars = 0

        # Safe bounded overlap parameter
        effective_overlap = max(0, min(self.overlap_chars, self.max_chunk_chars // 2))

        def flush_accumulator(retain_overlap: bool = False):
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

            # Heuristic token count estimation
            token_count = estimate_token_count(chunk_text)

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

            # Determine trailing overlap elements if within the same section
            if retain_overlap and effective_overlap > 0 and len(accum_elements) > 1:
                overlap_elems: List[DocumentElement] = []
                overlap_len = 0
                for e in reversed(accum_elements[1:]):  # Never retain the entire chunk
                    if e.element_type in (ElementType.HEADING, ElementType.TABLE):
                        break
                    e_len = len(e.text)
                    if overlap_len + e_len <= effective_overlap or not overlap_elems:
                        overlap_elems.insert(0, e)
                        overlap_len += e_len
                    else:
                        break
                accum_elements = overlap_elems
                accum_chars = sum(len(e.text) for e in overlap_elems)
            else:
                accum_elements = []
                accum_chars = 0

        for elem in doc.elements:
            elem_len = len(elem.text)

            if elem.element_type == ElementType.HEADING:
                # Heading marks a strong structural boundary.
                flush_accumulator(retain_overlap=False)

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
                flush_accumulator(retain_overlap=False)
                accum_elements.append(elem)
                flush_accumulator(retain_overlap=False)
                continue

            # Check if adding this element would exceed max chunk size OR target size
            if accum_elements and (accum_chars + elem_len > self.max_chunk_chars or accum_chars >= self.target_chunk_chars):
                flush_accumulator(retain_overlap=True)

            accum_elements.append(elem)
            accum_chars += elem_len

        flush_accumulator(retain_overlap=False)
        return chunks
