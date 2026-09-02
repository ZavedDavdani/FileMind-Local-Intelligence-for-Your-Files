"""Tests for Batch A3: Chunking & Evidence Integrity Hardening.

Verifies:
1. One explicit semantic definition for approximate token_count (estimate_token_count).
2. Production and evaluation token count consistency across ASCII, Unicode, CJK, whitespace, punctuation, empty strings.
3. Deterministic character-based chunk overlap within sections, strictly respecting heading and table boundaries.
4. Pathological overlap bounds (negative, zero, overly large overlap).
5. Monotonic, unique document element IDs in Markdown parser with interleaved tables, paragraphs, headings, code fences.
6. Delimiter-safe canonical chunk identity serialization (resolves colon ambiguity in headings).
7. ChunkProvenance runtime immutability (frozen=True).
8. TableData.to_markdown pipe escaping without double-escaping or structure corruption.
"""

from dataclasses import FrozenInstanceError
import tempfile
import pytest

from app.intelligence.chunker.hierarchical import (
    CHUNKER_VERSION,
    HierarchicalChunker,
    estimate_token_count,
)
from app.intelligence.chunker.identity import (
    compute_chunk_content_hash,
    generate_chunk_id,
)
from app.intelligence.chunker.provenance import ChunkProvenance
from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
    TableData,
)
from app.intelligence.parsers.text_parser import TextAndCodeParser


# =============================================================================
# 1. Token Count Semantic Contract
# =============================================================================

def test_1_token_count_empty_and_whitespace():
    """Verifies that empty strings and whitespace-only strings evaluate to 0 tokens."""
    assert estimate_token_count("") == 0
    assert estimate_token_count("   ") == 0
    assert estimate_token_count("\n\t  \r\n") == 0


def test_2_token_count_ascii_and_short_text():
    """Verifies approximate token estimation for standard ASCII and short text."""
    # Non-empty strings have a minimum token count of 1
    assert estimate_token_count("a") == 1
    assert estimate_token_count("Hello") == 1
    # ~4 chars per token for Latin text
    assert estimate_token_count("FileMind local search intelligence") == 8
    # Punctuation included in character count
    assert estimate_token_count("123, 456; 789! @#$%") == 4


def test_3_token_count_cjk_characters():
    """Verifies that CJK characters are estimated at ~1 token per ideograph/syllable."""
    # Chinese (15 ideographs)
    zh_text = "人工智能 是 计算机 科学 的 重要 分支。"
    zh_tokens = estimate_token_count(zh_text)
    assert zh_tokens >= 15

    # Japanese (Kanji + Katakana + Hiragana)
    ja_text = "ファイル 検索 システム と 機械 学習 モデル"
    ja_tokens = estimate_token_count(ja_text)
    assert ja_tokens >= 18

    # Korean (Hangul syllables)
    ko_text = "인공지능 기반 파일 검색 시스템"
    ko_tokens = estimate_token_count(ko_text)
    assert ko_tokens >= 13


def test_4_token_count_mixed_latin_cjk():
    """Verifies token estimation on mixed Latin and CJK sentences."""
    mixed_text = "FileMind 智能搜索 SQLite-Vec FastEmbed ハイブリッド 검색"
    tokens = estimate_token_count(mixed_text)
    assert tokens >= 15


def test_5_token_count_production_and_evaluation_consistency():
    """Verifies that production chunking and test evaluation use the exact same token estimation function."""
    content = "人工智能 是 计算机 科学 的 重要 分支。 深度 学习 在 自然 语言 处理 中 广泛 应用。"
    expected_tokens = estimate_token_count(content)

    doc = Document(
        file_id="f_eval_1",
        source_path="/tmp/eval.txt",
        filename="eval.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(element_id="e1", element_type=ElementType.PARAGRAPH, text=content)
        ],
    )
    chunker = HierarchicalChunker()
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].token_count == expected_tokens


# =============================================================================
# 2. Chunk Overlap Semantics & Bounds
# =============================================================================

def test_6_overlap_zero_produces_non_overlapping_chunks():
    """Verifies that overlap_chars=0 generates non-overlapping chunk boundaries."""
    doc = Document(
        file_id="f_doc_1",
        source_path="/tmp/test.txt",
        filename="test.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(element_id="e1", element_type=ElementType.PARAGRAPH, text="Paragraph A " * 100),  # ~1200 chars
            DocumentElement(element_id="e2", element_type=ElementType.PARAGRAPH, text="Paragraph B " * 100),  # ~1200 chars
            DocumentElement(element_id="e3", element_type=ElementType.PARAGRAPH, text="Paragraph C " * 100),  # ~1200 chars
        ],
    )
    chunker = HierarchicalChunker(target_chunk_chars=1500, max_chunk_chars=2500, overlap_chars=0)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) >= 2
    assert "Paragraph A" in chunks[0].content
    assert "Paragraph C" in chunks[-1].content
    assert "Paragraph A" not in chunks[-1].content


def test_7_overlap_nonzero_retains_trailing_elements_within_section():
    """Verifies that non-zero overlap retains trailing elements in subsequent chunks within the same section."""
    p1 = "First paragraph content. " * 30   # ~750 chars
    p2 = "Second paragraph content. " * 35  # ~910 chars
    p3 = "Third paragraph content. " * 30   # ~750 chars

    doc = Document(
        file_id="f_doc_2",
        source_path="/tmp/test2.txt",
        filename="test2.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(element_id="e1", element_type=ElementType.PARAGRAPH, text=p1),
            DocumentElement(element_id="e2", element_type=ElementType.PARAGRAPH, text=p2),
            DocumentElement(element_id="e3", element_type=ElementType.PARAGRAPH, text=p3),
        ],
    )
    # Target 1500, Overlap 950:
    # Elements p1 (750) + p2 (910) = 1660 chars.
    # When p3 arrives, 1660 >= 1500 -> flushes Chunk 0 with [p1, p2].
    # Overlap 950 retains p2 (910 chars <= 950) for Chunk 1.
    # Chunk 1 gets [p2, p3].
    chunker = HierarchicalChunker(target_chunk_chars=1500, max_chunk_chars=2500, overlap_chars=950)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 2
    assert "First paragraph" in chunks[0].content
    assert "Second paragraph" in chunks[0].content
    assert "Second paragraph" in chunks[1].content
    assert "Third paragraph" in chunks[1].content
    assert "First paragraph" not in chunks[1].content
    assert chunks[0].chunk_id != chunks[1].chunk_id


def test_8_overlap_does_not_cross_heading_boundaries():
    """Verifies that structural heading boundaries strictly prevent overlap leaking across sections."""
    p1 = "Section 1 body content. " * 60  # ~1440 chars
    p2 = "Section 2 body content. " * 60  # ~1440 chars

    doc = Document(
        file_id="f_doc_3",
        source_path="/tmp/test3.txt",
        filename="test3.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(element_id="e1", element_type=ElementType.HEADING, text="Heading 1", level=1),
            DocumentElement(element_id="e2", element_type=ElementType.PARAGRAPH, text=p1),
            DocumentElement(element_id="e3", element_type=ElementType.HEADING, text="Heading 2", level=1),
            DocumentElement(element_id="e4", element_type=ElementType.PARAGRAPH, text=p2),
        ],
    )
    chunker = HierarchicalChunker(target_chunk_chars=1000, overlap_chars=500)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 2
    assert chunks[0].section == "Heading 1"
    assert "Section 1 body" in chunks[0].content
    assert "Section 2 body" not in chunks[0].content

    assert chunks[1].section == "Heading 2"
    assert "Section 2 body" in chunks[1].content
    assert "Section 1 body" not in chunks[1].content


def test_9_overlap_does_not_split_or_duplicate_tables():
    """Verifies that table elements are preserved intact and never duplicated via overlap."""
    t_data = TableData(headers=["Col1", "Col2"], rows=[["Val1", "Val2"]])
    p1 = "Paragraph preceding table. " * 40

    doc = Document(
        file_id="f_doc_4",
        source_path="/tmp/test4.txt",
        filename="test4.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(element_id="e1", element_type=ElementType.PARAGRAPH, text=p1),
            DocumentElement(element_id="e2", element_type=ElementType.TABLE, text=t_data.to_markdown(), table_data=t_data),
            DocumentElement(element_id="e3", element_type=ElementType.PARAGRAPH, text="Paragraph after table."),
        ],
    )
    chunker = HierarchicalChunker(target_chunk_chars=500, overlap_chars=200)
    chunks = chunker.chunk_document(doc)

    table_chunks = [c for c in chunks if c.content_type == "table"]
    assert len(table_chunks) == 1
    assert "Col1" in table_chunks[0].content


def test_10_overlap_pathological_configurations():
    """Verifies that negative, zero, and excessively large overlap values are bounded safely."""
    p1 = "Content paragraph 1. " * 40
    p2 = "Content paragraph 2. " * 40

    doc = Document(
        file_id="f_doc_5",
        source_path="/tmp/test5.txt",
        filename="test5.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(element_id="e1", element_type=ElementType.PARAGRAPH, text=p1),
            DocumentElement(element_id="e2", element_type=ElementType.PARAGRAPH, text=p2),
        ],
    )
    # Negative overlap
    c_neg = HierarchicalChunker(target_chunk_chars=500, overlap_chars=-100)
    chunks_neg = c_neg.chunk_document(doc)
    assert len(chunks_neg) >= 1

    # Overlap >= target_chunk_chars (bounded to target_chunk_chars // 2)
    c_huge = HierarchicalChunker(target_chunk_chars=500, overlap_chars=50000)
    chunks_huge = c_huge.chunk_document(doc)
    assert len(chunks_huge) >= 1
    # Check no duplicate chunk IDs
    chunk_ids = [c.chunk_id for c in chunks_huge]
    assert len(chunk_ids) == len(set(chunk_ids))


def test_11_overlap_small_document():
    """Verifies single-chunk small documents remain valid single chunks."""
    doc = Document(
        file_id="f_doc_6",
        source_path="/tmp/test6.txt",
        filename="test6.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(element_id="e1", element_type=ElementType.PARAGRAPH, text="Small single paragraph.")
        ],
    )
    chunker = HierarchicalChunker(target_chunk_chars=1500, overlap_chars=200)
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0


# =============================================================================
# 3. Markdown Table Element IDs & Monotonic Sequence
# =============================================================================

def test_12_markdown_element_ids_monotonic_and_unique_with_tables():
    """Verifies that interleaving tables, headings, paragraphs, and code blocks produces strictly monotonic, collision-free element IDs."""
    parser = TextAndCodeParser()
    md_text = (
        "Initial introductory paragraph.\n\n"
        "# Section 1: Data\n\n"
        "| ID | Name |\n"
        "|---|---|\n"
        "| 1 | Alpha |\n\n"
        "Paragraph following first table.\n\n"
        "| Metric | Score |\n"
        "|---|---|\n"
        "| Speed | 99 |\n\n"
        "```python\n"
        "print('code fence')\n"
        "```\n\n"
        "| Trailing | Table |\n"
        "|---|---|\n"
        "| End | True |\n"
    )

    with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as f:
        f.write(md_text.encode("utf-8"))
        f_path = f.name

    doc = parser.parse(f_path, "f_elem_test", "text/markdown")

    element_ids = [e.element_id for e in doc.elements]
    expected_ids = [f"f_elem_test_elem_{i}" for i in range(1, len(doc.elements) + 1)]

    # 1. Total elements count
    assert len(doc.elements) == 7
    # 2. Strict monotonicity and exact expected sequence
    assert element_ids == expected_ids
    # 3. Zero duplicates
    assert len(element_ids) == len(set(element_ids))


def test_13_markdown_table_with_escaped_pipes_in_cells():
    """Verifies that markdown table parsing preserves escaped pipes inside table cells."""
    parser = TextAndCodeParser()
    md_text = (
        "| Option | Description |\n"
        "|---|---|\n"
        "| CPU \\| GPU | Hardware accelerator choice |\n"
        "| Mode A | Normal operation |\n"
    )
    with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as f:
        f.write(md_text.encode("utf-8"))
        f_path = f.name

    doc = parser.parse(f_path, "f_pipe_test", "text/markdown")
    table_elems = [e for e in doc.elements if e.element_type == ElementType.TABLE]
    assert len(table_elems) == 1
    t_data = table_elems[0].table_data
    assert t_data is not None
    assert len(t_data.rows) == 2
    # Cell with pipe preserved without splitting into 3 columns
    assert len(t_data.rows[0]) == 2
    assert "CPU | GPU" in t_data.rows[0][0]


# =============================================================================
# 4. Chunk Identity Serialization & Collision Resistance
# =============================================================================

def test_14_chunk_identity_deterministic_same_inputs():
    """Verifies that identical semantic inputs produce identical chunk identifiers."""
    id1 = generate_chunk_id("file_123", "Heading A", "Heading B", 0, "hash_abc")
    id2 = generate_chunk_id("file_123", "Heading A", "Heading B", 0, "hash_abc")
    assert id1 == id2
    assert id1.startswith("chk_")
    assert len(id1) == 20  # "chk_" (4) + 16 hex chars = 20


def test_15_chunk_identity_delimiter_disambiguation():
    """Verifies that colon-containing headings produce distinct chunk IDs (resolving naive concatenation collisions)."""
    # Case A: h1 = "A:B", h2 = "C"
    id_a = generate_chunk_id("file_1", "A:B", "C", 0, "hash_1")
    # Case B: h1 = "A", h2 = "B:C"
    id_b = generate_chunk_id("file_1", "A", "B:C", 0, "hash_1")
    # Case C: h1 = "A:B:C", h2 = None
    id_c = generate_chunk_id("file_1", "A:B:C", None, 0, "hash_1")

    assert id_a != id_b
    assert id_a != id_c
    assert id_b != id_c


def test_16_chunk_identity_empty_and_unicode_headings():
    """Verifies chunk identity generation with None, empty strings, and Unicode characters."""
    id_none = generate_chunk_id("file_u", None, None, 0, "hash_u")
    id_empty = generate_chunk_id("file_u", "", "", 0, "hash_u")
    assert id_none == id_empty  # None and empty normalized to ""

    id_unicode = generate_chunk_id("file_u", "タイトル (Title)", "セクション (Section)", 1, "hash_u2")
    assert id_unicode.startswith("chk_")
    assert len(id_unicode) == 20


# =============================================================================
# 5. Provenance Immutability (frozen=True)
# =============================================================================

def test_17_chunk_provenance_frozen_dataclass_raises_on_mutation():
    """Verifies that mutating any field on ChunkProvenance raises FrozenInstanceError at runtime."""
    chunk = ChunkProvenance(
        chunk_id="chk_test_1",
        file_id="f_1",
        source_file="test.txt",
        source_path="/tmp/test.txt",
        content="Test content",
        token_count=2,
    )

    with pytest.raises(FrozenInstanceError):
        chunk.token_count = 10  # type: ignore

    with pytest.raises(FrozenInstanceError):
        chunk.content = "New mutated content"  # type: ignore

    with pytest.raises(FrozenInstanceError):
        chunk.chunk_id = "chk_mutated"  # type: ignore


def test_18_chunk_provenance_to_dict_and_equality():
    """Verifies that ChunkProvenance serializes to dict and supports value equality."""
    chunk1 = ChunkProvenance(
        chunk_id="chk_1",
        file_id="f_1",
        source_file="test.txt",
        source_path="/tmp/test.txt",
        content="Content A",
        token_count=3,
    )
    chunk2 = ChunkProvenance(
        chunk_id="chk_1",
        file_id="f_1",
        source_file="test.txt",
        source_path="/tmp/test.txt",
        content="Content A",
        token_count=3,
    )
    assert chunk1 == chunk2
    assert hash(chunk1) == hash(chunk2)

    d = chunk1.to_dict()
    assert d["chunk_id"] == "chk_1"
    assert d["token_count"] == 3
    assert d["content"] == "Content A"


# =============================================================================
# 6. Table Markdown Escaping
# =============================================================================

def test_19_table_data_to_markdown_escapes_literal_pipes():
    """Verifies that literal pipe characters in headers and cells are escaped as \\|."""
    t = TableData(
        headers=["Model | Engine", "Mode"],
        rows=[
            ["SQLite | sqlite-vec", "Embedded | In-Process"],
            ["FastEmbed | ONNX", "Local | CPU"],
        ],
        caption="Tech Stack",
    )
    md = t.to_markdown()

    assert "| Model \\| Engine | Mode |" in md
    assert "| SQLite \\| sqlite-vec | Embedded \\| In-Process |" in md
    assert "| FastEmbed \\| ONNX | Local \\| CPU |" in md


def test_20_table_data_to_markdown_preserves_already_escaped_pipes():
    """Verifies that already-escaped pipes (\\|) are not double-escaped to \\\\\\|."""
    t = TableData(
        headers=["Pre-escaped"],
        rows=[["Value with \\| pre-escaped pipe"]],
    )
    md = t.to_markdown()
    assert "\\| pre-escaped" in md
    assert "\\\\\\|" not in md


def test_21_table_data_to_markdown_multiline_newlines_and_unicode():
    """Verifies that newlines in cells are replaced with spaces and Unicode with pipes is rendered cleanly."""
    t = TableData(
        headers=["Header\nWith\nNewlines", "Language | 言語"],
        rows=[
            ["Row 1\nCell content", "Japanese: 日本語 | Tokyo"],
        ],
    )
    md = t.to_markdown()
    assert "Header With Newlines" in md
    assert "Language \\| 言語" in md
    assert "Japanese: 日本語 \\| Tokyo" in md
