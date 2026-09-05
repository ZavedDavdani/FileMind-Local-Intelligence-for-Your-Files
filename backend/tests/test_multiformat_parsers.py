"""Tests for multiformat document, office, and structured markup parsers."""

import io
import json
from pathlib import Path
import pytest

from app.intelligence.detector import detect_file_format, EXTENSION_MIME_MAP
from app.intelligence.models import ElementType, Document
from app.intelligence.parsers.legacy_doc_ppt_parser import LegacyOfficeParser
from app.intelligence.parsers.pptx_parser import PptxParser
from app.intelligence.parsers.registry import default_parser_registry
from app.intelligence.parsers.rtf_html_parser import CleanHTMLParser, RtfAndHtmlParser
from app.intelligence.parsers.tabular_parser import TabularParser


class TestFormatDetector:
    def test_extension_mime_mapping_coverage(self):
        expected_exts = [
            ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".tsv",
            ".json", ".xml", ".html", ".htm", ".rtf", ".txt", ".md",
            ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".ico",
            ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma",
            ".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv",
        ]
        for ext in expected_exts:
            assert ext in EXTENSION_MIME_MAP, f"Missing extension in map: {ext}"

    def test_magic_byte_sniffing(self, tmp_path):
        # PNG magic
        png_file = tmp_path / "test.unknown"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01")
        mime, fmt = detect_file_format(str(png_file))
        assert mime == "image/png"
        assert fmt == "IMAGE"

        # PDF magic
        pdf_file = tmp_path / "doc.unknown"
        pdf_file.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj")
        mime, fmt = detect_file_format(str(pdf_file))
        assert mime == "application/pdf"
        assert fmt == "PDF"

        # WAV magic
        wav_file = tmp_path / "audio.bin"
        wav_file.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
        mime, fmt = detect_file_format(str(wav_file))
        assert mime == "audio/wav"
        assert fmt == "AUDIO"


class TestTabularParser:
    def test_csv_with_sniffer_and_provenance(self, tmp_path):
        csv_file = tmp_path / "sales.csv"
        csv_content = (
            "Region,Quarter,Revenue,Target\n"
            "North,Q1,150000,140000\n"
            "North,Q2,165000,150000\n"
            "South,Q1,120000,130000\n"
            "South,Q2,145000,140000\n"
        )
        csv_file.write_text(csv_content, encoding="utf-8")

        parser = TabularParser()
        doc = parser.parse(csv_file, file_id="file-csv-1", mime_type="text/csv")

        assert doc.parser_name == "tabular-parser"
        tables = [e for e in doc.elements if e.element_type == ElementType.TABLE]
        assert len(tables) >= 1
        el = tables[0]
        assert el.element_type == ElementType.TABLE
        assert el.sheet_name == "sales"
        assert "North" in el.text
        assert "Revenue" in el.text
        assert el.metadata.get("total_rows") == 4

    def test_tsv_parsing(self, tmp_path):
        tsv_file = tmp_path / "metrics.tsv"
        tsv_content = "Metric\tValue\tUnit\nLatency\t12.5\tms\nThroughput\t4500\trps\n"
        tsv_file.write_text(tsv_content, encoding="utf-8")

        parser = TabularParser()
        doc = parser.parse(tsv_file, file_id="file-tsv-1", mime_type="text/tab-separated-values")

        tables = [e for e in doc.elements if e.element_type == ElementType.TABLE]
        assert len(tables) >= 1
        assert tables[0].element_type == ElementType.TABLE
        assert "Latency" in tables[0].text
        assert "Throughput" in tables[0].text

    def test_xml_hierarchical_parsing(self, tmp_path):
        xml_file = tmp_path / "config.xml"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<project name="FileMind" version="1.0">\n'
            '  <settings>\n'
            '    <port>24823</port>\n'
            '    <integrity>NORMAL</integrity>\n'
            '  </settings>\n'
            '  <description>Local Intelligence for Your Files</description>\n'
            '</project>\n'
        )
        xml_file.write_text(xml_content, encoding="utf-8")

        parser = TabularParser()
        doc = parser.parse(xml_file, file_id="file-xml-1", mime_type="application/xml")

        assert len(doc.elements) >= 1
        combined = " ".join(e.text for e in doc.elements)
        assert "FileMind" in combined
        assert "24823" in combined
        assert "NORMAL" in combined

    def test_json_tree_parsing(self, tmp_path):
        json_file = tmp_path / "data.json"
        data = {
            "app": "FileMind",
            "features": ["multiformat", "multimodal", "local-first"],
            "config": {"port": 24823, "active": True}
        }
        json_file.write_text(json.dumps(data), encoding="utf-8")

        parser = TabularParser()
        doc = parser.parse(json_file, file_id="file-json-1", mime_type="application/json")

        assert len(doc.elements) >= 1
        combined = " ".join(e.text for e in doc.elements)
        assert "FileMind" in combined
        assert "multimodal" in combined


class TestRtfAndHtmlParser:
    def test_clean_html_strips_scripts_and_styles(self, tmp_path):
        html_file = tmp_path / "article.html"
        html_content = (
            "<!DOCTYPE html>\n"
            "<html>\n"
            '<head><title>FileMind Intelligence</title><style>.hidden { display: none; }</style></head>\n'
            "<body>\n"
            '  <nav><a href="/home">Home</a></nav>\n'
            "  <h1>Architecture Overview</h1>\n"
            "  <p>FileMind runs locally on port 24823 with zero cloud telemetry.</p>\n"
            "  <script>console.log('unwanted telemetry');</script>\n"
            "  <h2>Performance Tuning</h2>\n"
            "  <p>SQLite WAL mode provides concurrent read-write scaling.</p>\n"
            "</body>\n"
            "</html>\n"
        )
        html_file.write_text(html_content, encoding="utf-8")

        parser = RtfAndHtmlParser()
        doc = parser.parse(html_file, file_id="file-html-1", mime_type="text/html")

        assert doc.parser_name == "rtf-html-parser"
        combined = " ".join(e.text for e in doc.elements)
        assert "Architecture Overview" in combined
        assert "FileMind runs locally" in combined
        assert "SQLite WAL mode" in combined
        assert "console.log" not in combined
        assert "display: none" not in combined

    def test_rtf_text_extraction(self, tmp_path):
        rtf_file = tmp_path / "document.rtf"
        rtf_content = (
            "{\\\\rtf1\\\\ansi\\\\deff0"
            "{\\\\fonttbl{\\\\f0\\\\fnil\\\\fcharset0 Arial;}}"
            "{\\\\colortbl ;\\\\red0\\\\green0\\\\blue0;}"
            "\\\\viewkind4\\\\uc1\\\\pard\\\\lang1033\\\\f0\\\\fs24 FileMind RTF Document Overview\\\\par\\\\par "
            "This paragraph contains grounded technical evidence extracted from RTF.\\\\par}"
        )
        rtf_file.write_text(rtf_content, encoding="utf-8")

        parser = RtfAndHtmlParser()
        doc = parser.parse(rtf_file, file_id="file-rtf-1", mime_type="application/rtf")

        assert len(doc.elements) >= 1
        combined = " ".join(e.text for e in doc.elements)
        assert "FileMind RTF Document Overview" in combined
        assert "grounded technical evidence" in combined


class TestLegacyOfficeParser:
    def test_safe_ole2_binary_stream_extraction(self, tmp_path):
        doc_file = tmp_path / "legacy_notes.doc"
        content_ascii = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE2 magic header
        content_ascii += b"\x00" * 32
        text1 = "Confidential Architecture Strategy for FileMind 2026".encode("utf-8")
        text2 = "Key Objective: Local Offline AI Vector Indexing".encode("utf-16le")
        doc_file.write_bytes(content_ascii + text1 + b"\x00\x00" + text2 + b"\x00" * 64)

        parser = LegacyOfficeParser()
        doc = parser.parse(doc_file, file_id="file-doc-1", mime_type="application/msword")

        assert doc.parser_name == "legacy-office-parser"
        assert len(doc.elements) >= 1
        combined = " ".join(e.text for e in doc.elements)
        assert "Confidential Architecture Strategy" in combined or "FileMind" in combined
        assert "Local Offline AI" in combined or "Vector Indexing" in combined


class TestRegistryCoverage:
    def test_all_multiformats_registered(self):
        extensions = [
            ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".tsv",
            ".json", ".xml", ".html", ".htm", ".rtf", ".txt", ".md",
            ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".svg",
            ".mp3", ".wav", ".m4a", ".flac", ".ogg",
            ".mp4", ".mkv", ".mov", ".avi", ".webm",
        ]
        for ext in extensions:
            parser = default_parser_registry.get_parser_for_file(f"sample{ext}")
            assert parser is not None, f"No parser registered for extension: {ext}"
