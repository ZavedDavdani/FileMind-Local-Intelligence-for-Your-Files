"""Tests for hierarchical chunking: heading association, table integrity, and structural boundaries."""

import tempfile
import pytest

from app.intelligence.chunker.hierarchical import HierarchicalChunker
from app.intelligence.parsers.docx_parser import DocxParser
from app.intelligence.parsers.pdf_parser import PyMuPDFParser
from app.intelligence.parsers.text_parser import TextAndCodeParser
from tests.fixtures.realistic_corpus import generate_realistic_structural_corpus


@pytest.fixture(scope="module")
def corpus_files():
    with tempfile.TemporaryDirectory() as tmp_dir:
        fixtures = generate_realistic_structural_corpus(tmp_dir)
        yield fixtures


def test_hierarchical_chunking_heading_association(corpus_files):
    md_path = corpus_files["MARKDOWN"]
    parser = TextAndCodeParser()
    doc = parser.parse(md_path, file_id="file_md_test")

    chunker = HierarchicalChunker(target_chunk_chars=300, max_chunk_chars=600)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) >= 3
    # Check that chunks under # FileMind Engine Specification -> ## Subsystems have h1_parent set
    subsystem_chunks = [c for c in chunks if "Subsystems" in (c.section or "") or "Subsystems" in (c.h2_parent or "")]
    for chk in subsystem_chunks:
        assert chk.h1_parent is not None
        assert "FileMind Engine Specification" in chk.h1_parent


def test_table_integrity_in_chunks(corpus_files):
    docx_path = corpus_files["DOCX"]
    parser = DocxParser()
    doc = parser.parse(docx_path, file_id="file_docx_test")

    chunker = HierarchicalChunker(target_chunk_chars=400, max_chunk_chars=800)
    chunks = chunker.chunk_document(doc)

    table_chunks = [c for c in chunks if c.content_type == "table"]
    assert len(table_chunks) >= 1
    t_chunk = table_chunks[0]

    # Verify table headers and rows are completely intact inside the single chunk
    assert "| Component | Layer | Persistence |" in t_chunk.content
    assert "| Watcher | Filesystem | SQLite file_events |" in t_chunk.content
    assert "| WorkerPool | Engine | SQLite indexing_jobs |" in t_chunk.content
    assert "| ChunkStore | Intelligence | SQLite chunks |" in t_chunk.content


def test_pdf_chunking_page_and_heading_preservation(corpus_files):
    pdf_path = corpus_files["PDF"]
    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, file_id="file_pdf_test")

    chunker = HierarchicalChunker()
    chunks = chunker.chunk_document(doc)

    assert len(chunks) >= 2
    # Verify page numbers are preserved
    pages = {c.page for c in chunks if c.page is not None}
    assert 1 in pages
    assert 2 in pages
