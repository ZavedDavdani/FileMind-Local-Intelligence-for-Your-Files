"""Regression tests for Batch 2: Filesystem, Parsers & Security Hardening."""

import os
import tempfile
import pytest

from app.intelligence.models import ElementType
from app.intelligence.parsers.registry import ParserRegistry, default_parser_registry
from app.intelligence.parsers.text_parser import TextAndCodeParser
from app.intelligence.parsers.tabular_parser import TabularParser
from app.intelligence.parsers.pptx_parser import PptxParser
from app.intelligence.detector import detect_file_format


def test_unclosed_markdown_code_fence_preserved_at_eof():
    """Unclosed markdown code fences at EOF must not silently drop the code content."""
    parser = TextAndCodeParser()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# Introduction\n\nSome text.\n\n```python\ndef calculate_total(a, b):\n    return a + b\n")
        f_path = f.name

    try:
        doc = parser.parse(f_path, file_id="file_unclosed_md")
        code_blocks = [e for e in doc.elements if e.element_type == ElementType.CODE_BLOCK]
        assert len(code_blocks) == 1
        assert "def calculate_total" in code_blocks[0].text
        assert code_blocks[0].language == "python"
        assert code_blocks[0].line_start == 5
    finally:
        os.remove(f_path)


def test_go_source_structural_detection():
    """Go source code files must extract structs and functions into structural headings."""
    parser = TextAndCodeParser()
    go_content = """package main

import "fmt"

type ServerConfig struct {
    Host string
    Port int
}

func NewServer(cfg ServerConfig) *ServerConfig {
    return &cfg
}

func (s *ServerConfig) Start() error {
    fmt.Println("Server starting...")
    return nil
}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False, encoding="utf-8") as f:
        f.write(go_content)
        f_path = f.name

    try:
        doc = parser.parse(f_path, file_id="file_go_1")
        headings = [e for e in doc.elements if e.element_type == ElementType.HEADING]
        heading_texts = [h.text for h in headings]

        assert any("type ServerConfig struct" in h for h in heading_texts)
        assert any("func NewServer" in h for h in heading_texts)
        assert any("func (s *ServerConfig) Start() error" in h for h in heading_texts)
    finally:
        os.remove(f_path)


def test_parser_registry_caching_and_extension_coverage():
    """Parser registry must cache parser instances across all mapped extensions to prevent repeated instantiation."""
    registry = ParserRegistry()
    call_count = 0

    def mock_factory():
        nonlocal call_count
        call_count += 1
        return TextAndCodeParser()

    registry.register_factory(mock_factory, [".txt", ".hpp", ".toml"], ["text/plain"])

    # First access creates instance
    p1 = registry.get_parser_for_file("file.hpp")
    assert p1 is not None
    assert call_count == 1

    # Second access with another extension from the same factory must use cached instance
    p2 = registry.get_parser_for_file("config.toml")
    assert p2 is p1
    assert call_count == 1


def test_detector_c_and_cpp_headers_format():
    """C/C++ header files (.h, .hpp) must detect as CODE format."""
    mime_h, fmt_h = detect_file_format("include/header.h")
    assert fmt_h == "CODE"

    mime_hpp, fmt_hpp = detect_file_format("include/header.hpp")
    assert fmt_hpp == "CODE"


def test_xlsx_provenance_lines_present():
    """XLSX worksheet tables must include line_start and line_end provenance."""
    import openpyxl

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f_path = f.name

    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Financials"
        ws.append(["Quarter", "Revenue", "Margin"])
        ws.append(["Q1", "$10M", "25%"])
        ws.append(["Q2", "$12M", "28%"])
        wb.save(f_path)
        wb.close()

        parser = TabularParser()
        doc = parser.parse(f_path, file_id="file_xlsx_1", mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        tables = [e for e in doc.elements if e.element_type == ElementType.TABLE]
        assert len(tables) == 1
        assert tables[0].line_start == 1
        assert tables[0].line_end == 3
    finally:
        os.remove(f_path)
