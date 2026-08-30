"""Tests for format-specific document parsers: structural preservation, headings, tables, and offsets."""

import os
import tempfile
import pytest

from app.intelligence.detector import detect_file_format, is_supported_document
from app.intelligence.models import ElementType
from app.intelligence.parsers.docx_parser import DocxParser
from app.intelligence.parsers.pdf_parser import PyMuPDFParser, PyPDFParser
from app.intelligence.parsers.pptx_parser import PptxParser
from app.intelligence.parsers.tabular_parser import TabularParser
from app.intelligence.parsers.text_parser import TextAndCodeParser
from tests.fixtures.realistic_corpus import generate_realistic_structural_corpus


@pytest.fixture(scope="module")
def corpus_files():
    with tempfile.TemporaryDirectory() as tmp_dir:
        fixtures = generate_realistic_structural_corpus(tmp_dir)
        yield fixtures


# -----------------------------------------------------------------------------
# PDF Parser Tests (PyMuPDF)
# -----------------------------------------------------------------------------

def test_pdf_structure_preservation(corpus_files):
    pdf_path = corpus_files["PDF"]
    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, file_id="file_pdf_1")

    assert doc.file_id == "file_pdf_1"
    assert doc.total_pages == 2
    assert len(doc.elements) >= 5
    assert any(e.element_type == ElementType.HEADING for e in doc.elements)
    assert any(e.element_type == ElementType.TABLE for e in doc.elements)
    assert any(e.element_type == ElementType.PARAGRAPH for e in doc.elements)


def test_pdf_heading_hierarchy(corpus_files):
    pdf_path = corpus_files["PDF"]
    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, file_id="file_pdf_1")

    headings = doc.headings
    heading_texts = [h.text for h in headings]
    assert any("System Architecture Specification" in t for t in heading_texts)
    assert any("Component Overview" in t for t in heading_texts)
    assert any("Storage Engine Specifications" in t for t in heading_texts)


def test_pdf_table_preservation(corpus_files):
    pdf_path = corpus_files["PDF"]
    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, file_id="file_pdf_1")

    tables = doc.tables
    assert len(tables) >= 1
    t_elem = tables[0]
    assert t_elem.table_data is not None
    assert "Subsystem" in t_elem.table_data.headers or any("Subsystem" in r for r in t_elem.table_data.rows)
    assert t_elem.page_number == 1


# -----------------------------------------------------------------------------
# DOCX Parser Tests
# -----------------------------------------------------------------------------

def test_docx_structure_preservation(corpus_files):
    docx_path = corpus_files["DOCX"]
    parser = DocxParser()
    doc = parser.parse(docx_path, file_id="file_docx_1")

    assert doc.total_pages is None or doc.total_pages >= 1
    assert len(doc.elements) >= 4


def test_docx_heading_hierarchy(corpus_files):
    docx_path = corpus_files["DOCX"]
    parser = DocxParser()
    doc = parser.parse(docx_path, file_id="file_docx_1")

    headings = doc.headings
    h1s = [h for h in headings if h.level == 1]
    h2s = [h for h in headings if h.level == 2]
    assert len(h1s) >= 2
    assert any("System Architecture Specification" in h.text for h in h1s)
    assert any("Component Overview" in h.text for h in h2s)


def test_docx_table_preservation(corpus_files):
    docx_path = corpus_files["DOCX"]
    parser = DocxParser()
    doc = parser.parse(docx_path, file_id="file_docx_1")

    tables = doc.tables
    assert len(tables) >= 1
    tbl = tables[0].table_data
    assert tbl.headers == ["Component", "Layer", "Persistence"]
    assert len(tbl.rows) == 3
    assert tbl.rows[0] == ["Watcher", "Filesystem", "SQLite file_events"]


# -----------------------------------------------------------------------------
# PPTX Parser Tests
# -----------------------------------------------------------------------------

def test_pptx_structure_preservation(corpus_files):
    pptx_path = corpus_files["PPTX"]
    parser = PptxParser()
    doc = parser.parse(pptx_path, file_id="file_pptx_1")

    assert doc.total_pages == 2
    headings = doc.headings
    assert any("Slide 1" in h.text for h in headings)
    assert any("Slide 2" in h.text for h in headings)


# -----------------------------------------------------------------------------
# Markdown & Source Code Parser Tests
# -----------------------------------------------------------------------------

def test_markdown_structure_preservation(corpus_files):
    md_path = corpus_files["MARKDOWN"]
    parser = TextAndCodeParser()
    doc = parser.parse(md_path, file_id="file_md_1")

    headings = doc.headings
    assert len(headings) >= 4
    h_texts = [h.text for h in headings]
    assert "FileMind Engine Specification" in h_texts
    assert "Overview" in h_texts
    assert "Subsystems" in h_texts

    # Verify code block extraction
    code_blocks = [e for e in doc.elements if e.element_type == ElementType.CODE_BLOCK]
    assert len(code_blocks) >= 1
    assert "def get_config():" in code_blocks[0].text
    assert code_blocks[0].language == "python"

    # Verify table extraction
    tables = doc.tables
    assert len(tables) >= 1
    assert "Watcher" in tables[0].text


def test_source_code_preservation(corpus_files):
    py_path = corpus_files["CODE"]
    parser = TextAndCodeParser()
    doc = parser.parse(py_path, file_id="file_py_1")

    headings = doc.headings
    assert any("class EngineCoordinator" in h.text for h in headings)
    assert any("def initialize" in h.text or "def execute_task" in h.text for h in headings)


# -----------------------------------------------------------------------------
# Tabular Parser Tests (CSV, JSON, XLSX)
# -----------------------------------------------------------------------------

def test_tabular_csv_json_xlsx_preservation(corpus_files):
    parser = TabularParser()

    # CSV
    doc_csv = parser.parse(corpus_files["CSV"], file_id="file_csv_1")
    assert len(doc_csv.tables) == 1
    assert doc_csv.tables[0].table_data.headers == ["metric_name", "category", "target_val", "unit"]

    # JSON
    doc_json = parser.parse(corpus_files["JSON"], file_id="file_json_1")
    assert len(doc_json.tables) == 1 or len(doc_json.elements) >= 3

    # XLSX
    doc_xlsx = parser.parse(corpus_files["XLSX"], file_id="file_xlsx_1")
    assert doc_xlsx.total_pages == 2
    assert len(doc_xlsx.tables) == 2
