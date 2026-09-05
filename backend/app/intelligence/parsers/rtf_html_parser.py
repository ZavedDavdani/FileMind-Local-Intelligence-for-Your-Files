"""HTML and RTF parser preserving headings, paragraphs, and tables."""

import html.parser
import os
import re
from typing import List, Optional

from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
    TableData,
)
from app.intelligence.parsers.base import BaseParser, CorruptedDocumentError
from app.intelligence.parsers.decoder import read_text_file_strictly

RTF_HTML_PARSER_VERSION = "1.0.0"


class CleanHTMLParser(html.parser.HTMLParser):
    """Extracts semantic headings, paragraphs, lists, and tables while stripping noise."""

    def __init__(self):
        super().__init__()
        self.elements_data: List[tuple] = []  # ('HEADING', level, text) | ('PARAGRAPH', text) | ('TABLE', headers, rows)
        self._current_tag = None
        self._current_text = []
        self._skip_depth = 0
        self._in_heading = False
        self._heading_level = 1
        self._in_table = False
        self._table_headers = []
        self._table_rows = []
        self._current_row = []
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "nav", "header", "footer", "aside", "noscript", "svg"):
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush_text()
            self._in_heading = True
            self._heading_level = int(tag_lower[1])
        elif tag_lower == "p":
            self._flush_text()
        elif tag_lower == "table":
            self._flush_text()
            self._in_table = True
            self._table_headers = []
            self._table_rows = []
        elif tag_lower == "tr":
            self._current_row = []
        elif tag_lower in ("th", "td"):
            self._in_cell = True
            self._current_text = []

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "nav", "header", "footer", "aside", "noscript", "svg"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._skip_depth > 0:
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = "".join(self._current_text).strip()
            if text:
                self.elements_data.append(("HEADING", self._heading_level, text))
            self._current_text = []
            self._in_heading = False
        elif tag_lower == "p":
            self._flush_text()
        elif tag_lower in ("th", "td"):
            cell_text = "".join(self._current_text).strip()
            self._current_row.append(cell_text)
            self._current_text = []
            self._in_cell = False
        elif tag_lower == "tr":
            if self._current_row:
                if not self._table_headers and any(self._current_row):
                    self._table_headers = list(self._current_row)
                else:
                    self._table_rows.append(list(self._current_row))
            self._current_row = []
        elif tag_lower == "table":
            if self._table_headers or self._table_rows:
                self.elements_data.append(("TABLE", self._table_headers, self._table_rows))
            self._in_table = False

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._current_text.append(data)

    def _flush_text(self):
        text = "".join(self._current_text).strip()
        if text and not self._in_heading and not self._in_table:
            self.elements_data.append(("PARAGRAPH", text))
        self._current_text = []


def extract_rtf_text(rtf_content: str) -> List[str]:
    """Extracts plain text paragraphs from Rich Text Format streams."""
    # Strip RTF control words and groups
    text = rtf_content
    # Replace escaped hex chars 'xx
    text = re.sub(r"\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    # Remove control words e.g. \par, , onttbl
    text = re.sub(r"\\w+(?:-?\d+)?\s?", " ", text)
    # Remove braces
    text = re.sub(r"[{}]", "", text)
    # Split into clean paragraphs
    paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
    return paragraphs


class RtfAndHtmlParser(BaseParser):
    """Parser for HTML (.html, .htm) and Rich Text Format (.rtf) documents."""

    @property
    def parser_name(self) -> str:
        return "rtf-html-parser"

    @property
    def parser_version(self) -> str:
        return RTF_HTML_PARSER_VERSION

    @property
    def supported_mime_types(self) -> List[str]:
        return ["text/html", "application/rtf"]

    @property
    def supported_extensions(self) -> List[str]:
        return [".html", ".htm", ".rtf"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "text/html") -> Document:
        file_path = str(file_path)
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

        raw_content = read_text_file_strictly(file_path, filename=filename)

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
            if ext == ".rtf":
                paras = extract_rtf_text(raw_content)
                for idx, p in enumerate(paras, start=1):
                    doc_obj.elements.append(
                        DocumentElement(
                            element_id=f"{file_id}_elem_{idx}",
                            element_type=ElementType.PARAGRAPH,
                            text=p,
                            media_type="document",
                            extraction_method="native",
                        )
                    )
            else:
                parser = CleanHTMLParser()
                parser.feed(raw_content)
                parser._flush_text()

                elem_idx = 0
                for item in parser.elements_data:
                    elem_idx += 1
                    kind = item[0]
                    if kind == "HEADING":
                        _, level, text = item
                        doc_obj.elements.append(
                            DocumentElement(
                                element_id=f"{file_id}_elem_{elem_idx}",
                                element_type=ElementType.HEADING,
                                text=text,
                                level=level,
                                media_type="document",
                                extraction_method="native",
                            )
                        )
                    elif kind == "TABLE":
                        _, headers, rows = item
                        t_data = TableData(headers=headers, rows=rows, caption=filename)
                        doc_obj.elements.append(
                            DocumentElement(
                                element_id=f"{file_id}_elem_{elem_idx}",
                                element_type=ElementType.TABLE,
                                text=t_data.to_markdown(),
                                table_data=t_data,
                                media_type="document",
                                extraction_method="native",
                            )
                        )
                    elif kind == "PARAGRAPH":
                        _, text = item
                        doc_obj.elements.append(
                            DocumentElement(
                                element_id=f"{file_id}_elem_{elem_idx}",
                                element_type=ElementType.PARAGRAPH,
                                text=text,
                                media_type="document",
                                extraction_method="native",
                            )
                        )
        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to parse HTML/RTF {filename}: {str(exc)}") from exc

        return doc_obj
