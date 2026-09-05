"""Normalized Document Model for FileMind Document Intelligence.

Provides a parser-independent internal representation preserving
hierarchical structure (H1/H2 headings), paragraphs, lists, tables,
code fences, and precise source-location metadata (page numbers, line numbers, character spans).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ElementType(str, Enum):
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    LIST_ITEM = "LIST_ITEM"
    TABLE = "TABLE"
    CODE_BLOCK = "CODE_BLOCK"
    PAGE_BREAK = "PAGE_BREAK"
    TRANSCRIPT_SEGMENT = "TRANSCRIPT_SEGMENT"
    IMAGE_CAPTION = "IMAGE_CAPTION"
    VISUAL_METADATA = "VISUAL_METADATA"


@dataclass
class TableData:
    """Structured representation of table cells."""
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    caption: Optional[str] = None

    def to_markdown(self) -> str:
        """Renders table as clean GitHub Flavored Markdown with escaped pipes."""
        import re

        def _escape_cell(cell: Any) -> str:
            text = str(cell if cell is not None else "").replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
            return re.sub(r"(?<!\\)\|", r"\|", text)

        lines = []
        if self.caption:
            lines.append(f"**Table: {self.caption}**\n")

        if self.headers:
            header_row = "| " + " | ".join(_escape_cell(h) for h in self.headers) + " |"
            separator = "| " + " | ".join("---" for _ in self.headers) + " |"
            lines.append(header_row)
            lines.append(separator)

        for row in self.rows:
            # Ensure row length matches headers if present
            row_cells = [_escape_cell(c) for c in row]
            if self.headers and len(row_cells) < len(self.headers):
                row_cells.extend([""] * (len(self.headers) - len(row_cells)))
            lines.append("| " + " | ".join(row_cells) + " |")

        return "\n".join(lines)


@dataclass
class DocumentElement:
    """Individual structural element within a document."""
    element_id: str
    element_type: ElementType
    text: str
    page_number: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    level: Optional[int] = None  # Heading level: 1 (H1), 2 (H2), 3 (H3), etc.
    table_data: Optional[TableData] = None
    language: Optional[str] = None  # For CODE_BLOCK
    parent_heading_id: Optional[str] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    frame_index: Optional[int] = None
    media_type: str = "document"  # 'document', 'image', 'audio', 'video', 'tabular'
    extraction_method: Optional[str] = None  # 'native', 'ocr', 'vision_description', 'transcription', 'metadata'
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """Parser-independent normalized document container."""
    file_id: str
    source_path: str
    filename: str
    mime_type: str
    title: Optional[str] = None
    total_pages: Optional[int] = None
    elements: List[DocumentElement] = field(default_factory=list)
    parser_name: str = "unknown"
    parser_version: str = "unknown"
    quality_assessment: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


    @property
    def full_text(self) -> str:
        """Concatenated text of all elements."""
        return "\n\n".join(e.text for e in self.elements if e.text.strip())

    @property
    def headings(self) -> List[DocumentElement]:
        """Returns all heading elements."""
        return [e for e in self.elements if e.element_type == ElementType.HEADING]

    @property
    def tables(self) -> List[DocumentElement]:
        """Returns all table elements."""
        return [e for e in self.elements if e.element_type == ElementType.TABLE]


__all__ = ["ElementType", "TableData", "DocumentElement", "Document"]
