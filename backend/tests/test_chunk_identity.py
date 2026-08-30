"""Tests for deterministic chunk identity and hashing strategy."""

import tempfile
from app.intelligence.chunker.hierarchical import HierarchicalChunker
from app.intelligence.chunker.identity import generate_chunk_id, compute_chunk_content_hash
from app.intelligence.parsers.text_parser import TextAndCodeParser


def test_deterministic_reprocessing_identity():
    """Verifies that processing the identical document twice generates identical chunk IDs."""
    content = "# Architecture\n\nThis is paragraph one.\n\n## Subsystem\n\nThis is paragraph two."
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(content)
        path = f.name

    parser = TextAndCodeParser()
    chunker = HierarchicalChunker()

    doc1 = parser.parse(path, file_id="file_identity_1")
    chunks1 = chunker.chunk_document(doc1)

    doc2 = parser.parse(path, file_id="file_identity_1")
    chunks2 = chunker.chunk_document(doc2)

    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2):
        assert c1.chunk_id == c2.chunk_id
        assert c1.content_hash == c2.content_hash
        assert c1.content == c2.content


def test_content_change_identity():
    """Verifies that modifying paragraph content produces a new chunk ID and hash."""
    content_v1 = "# Architecture\n\nOriginal content version 1."
    content_v2 = "# Architecture\n\nModified content version 2."

    parser = TextAndCodeParser()
    chunker = HierarchicalChunker()

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f1:
        f1.write(content_v1)
        path1 = f1.name

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f2:
        f2.write(content_v2)
        path2 = f2.name

    doc1 = parser.parse(path1, file_id="file_fixed_id")
    chunks1 = chunker.chunk_document(doc1)

    doc2 = parser.parse(path2, file_id="file_fixed_id")
    chunks2 = chunker.chunk_document(doc2)

    assert chunks1[0].chunk_id != chunks2[0].chunk_id
    assert chunks1[0].content_hash != chunks2[0].content_hash


def test_structure_change_identity():
    """Verifies that moving content under a different heading changes the chunk ID."""
    content_h1 = "# Section A\n\nShared body content."
    content_h2 = "# Section B\n\nShared body content."

    parser = TextAndCodeParser()
    chunker = HierarchicalChunker()

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f1:
        f1.write(content_h1)
        path1 = f1.name

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f2:
        f2.write(content_h2)
        path2 = f2.name

    doc1 = parser.parse(path1, file_id="file_struct_id")
    chunks1 = chunker.chunk_document(doc1)

    doc2 = parser.parse(path2, file_id="file_struct_id")
    chunks2 = chunker.chunk_document(doc2)

    # Even if body is similar, structural heading context changes chunk_id
    assert chunks1[0].h1_parent == "Section A"
    assert chunks2[0].h1_parent == "Section B"
    assert chunks1[0].chunk_id != chunks2[0].chunk_id
