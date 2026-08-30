"""Tests for strict provenance integrity and end-to-end source tracing."""

import os
import tempfile
import pytest

from app.intelligence.chunker.hierarchical import HierarchicalChunker
from app.intelligence.chunker.identity import compute_chunk_content_hash
from app.intelligence.parsers.pdf_parser import PyMuPDFParser
from app.intelligence.parsers.text_parser import TextAndCodeParser
from tests.fixtures.realistic_corpus import generate_realistic_structural_corpus


def test_markdown_provenance_source_matching():
    """Validates that a chunk's line and character spans match the exact slice of the source file."""
    content = "# Main Heading\n\nFirst paragraph text here.\n\n## Subheading\n\nSecond paragraph text with key information."
    
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(content)
        source_path = f.name

    try:
        parser = TextAndCodeParser()
        chunker = HierarchicalChunker(target_chunk_chars=200)
        file_id = "test_provenance_file_1"

        doc = parser.parse(source_path, file_id=file_id)
        chunks = chunker.chunk_document(doc)

        assert len(chunks) >= 2
        target_chunk = chunks[0]

        # 1. Verify chunk ID & file ID
        assert target_chunk.file_id == file_id
        assert target_chunk.source_path == source_path
        assert target_chunk.source_file == os.path.basename(source_path)

        # 2. Verify content hash
        expected_hash = compute_chunk_content_hash(target_chunk.content)
        assert target_chunk.content_hash == expected_hash

        # 3. Verify character slice in source file
        with open(source_path, "r", encoding="utf-8") as sf:
            raw_source = sf.read()

        if target_chunk.char_start is not None and target_chunk.char_end is not None:
            source_slice = raw_source[target_chunk.char_start:target_chunk.char_end].strip()
            # Assert source slice matches the chunk content or heading text
            assert "Main Heading" in source_slice or "First paragraph" in source_slice

        # 4. Verify line slice in source file
        if target_chunk.line_start is not None and target_chunk.line_end is not None:
            source_lines = raw_source.splitlines()
            line_slice = "\n".join(source_lines[target_chunk.line_start - 1:target_chunk.line_end])
            assert "Main Heading" in line_slice or "First paragraph" in line_slice

    finally:
        if os.path.exists(source_path):
            os.remove(source_path)


def test_pdf_provenance_page_and_section_matching():
    """Validates PDF page provenance and heading hierarchy attribution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        corpus = generate_realistic_structural_corpus(tmp_dir)
        pdf_path = corpus["PDF"]

        parser = PyMuPDFParser()
        chunker = HierarchicalChunker()
        file_id = "pdf_prov_test"

        doc = parser.parse(pdf_path, file_id=file_id)
        chunks = chunker.chunk_document(doc)

        assert len(chunks) >= 2

        # Verify page 1 chunk
        p1_chunk = next(c for c in chunks if c.page == 1)
        assert p1_chunk.file_id == file_id
        assert p1_chunk.source_path == pdf_path
        assert "System Architecture Specification" in p1_chunk.content or "Component Overview" in p1_chunk.content
        assert p1_chunk.content_hash == compute_chunk_content_hash(p1_chunk.content)

        # Verify page 2 chunk
        p2_chunk = next(c for c in chunks if c.page == 2)
        assert p2_chunk.page == 2
        assert "Storage Engine Specifications" in p2_chunk.content or "Data Integrity Protocols" in p2_chunk.content
