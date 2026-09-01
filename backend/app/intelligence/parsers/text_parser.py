"""Text, Markdown, and Source Code parser preserving line/character provenance."""

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


TEXT_PARSER_VERSION = "1.1.0"


class TextAndCodeParser(BaseParser):
    """
    Parser for Markdown, Plain Text, and Source Code files.
    Preserves heading hierarchies, code fences, markdown tables, lists, and line/character offsets.
    """

    @property
    def parser_name(self) -> str:
        return "text-code-parser"

    @property
    def parser_version(self) -> str:
        return TEXT_PARSER_VERSION


    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "text/plain",
            "text/markdown",
            "text/x-python",
            "application/javascript",
            "application/typescript",
            "text/x-rust",
            "text/x-go",
            "text/x-c",
            "text/x-c++",
            "text/x-java",
            "text/html",
            "text/css",
            "text/yaml",
            "application/xml",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [
            ".txt", ".md", ".markdown", ".log", ".py", ".js", ".ts",
            ".tsx", ".jsx", ".rs", ".go", ".c", ".cpp", ".h", ".java",
            ".html", ".css", ".yaml", ".yml", ".xml",
        ]

    def parse(self, file_path: str, file_id: str, mime_type: str = "text/plain") -> Document:
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to read text file: {str(exc)}") from exc

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

        lines = content.splitlines(keepends=True)
        if ext in (".md", ".markdown"):
            self._parse_markdown(lines, doc_obj, file_id)
        elif ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".c", ".cpp", ".java"):
            self._parse_source_code(lines, doc_obj, file_id, ext)
        else:
            self._parse_plain_text(lines, doc_obj, file_id)

        return doc_obj

    def _parse_markdown(self, lines: List[str], doc: Document, file_id: str):
        element_idx = 0
        current_h1_id = None
        current_h2_id = None

        char_offset = 0
        in_code_block = False
        code_block_lang = None
        code_lines = []
        code_start_line = 1
        code_char_start = 0

        in_table = False
        table_lines = []
        table_start_line = 1
        table_char_start = 0

        for line_num, raw_line in enumerate(lines, start=1):
            line_len = len(raw_line)
            line = raw_line.strip()

            # Handle Code Blocks (```)
            if line.startswith("```"):
                if in_code_block:
                    # Closing code block
                    in_code_block = False
                    code_text = "".join(code_lines).strip()
                    element_idx += 1
                    doc.elements.append(
                        DocumentElement(
                            element_id=f"{file_id}_elem_{element_idx}",
                            element_type=ElementType.CODE_BLOCK,
                            text=code_text,
                            language=code_block_lang,
                            line_start=code_start_line,
                            line_end=line_num,
                            char_start=code_char_start,
                            char_end=char_offset + line_len,
                            parent_heading_id=current_h2_id or current_h1_id,
                        )
                    )
                    code_lines = []
                    char_offset += line_len
                    continue
                else:
                    # Opening code block
                    in_code_block = True
                    code_block_lang = line[3:].strip() or None
                    code_lines = []
                    code_start_line = line_num
                    code_char_start = char_offset
                    char_offset += line_len
                    continue

            if in_code_block:
                code_lines.append(raw_line)
                char_offset += line_len
                continue

            # Handle Markdown Tables (| a | b |)
            if line.startswith("|") and line.endswith("|"):
                if not in_table:
                    in_table = True
                    table_lines = [line]
                    table_start_line = line_num
                    table_char_start = char_offset
                else:
                    table_lines.append(line)
                char_offset += line_len
                continue
            elif in_table:
                # Table ended
                in_table = False
                self._flush_markdown_table(table_lines, doc, file_id, element_idx, table_start_line, line_num - 1, table_char_start, char_offset, current_h2_id or current_h1_id)
                table_lines = []

            # Handle Headings (# Heading)
            if line.startswith("#"):
                match = re.match(r"^(#{1,6})\s+(.*)$", line)
                if match:
                    hashes, title = match.groups()
                    level = len(hashes)
                    element_idx += 1
                    elem_id = f"{file_id}_elem_{element_idx}"
                    parent_id = None
                    if level == 1:
                        current_h1_id = elem_id
                        current_h2_id = None
                    elif level == 2:
                        parent_id = current_h1_id
                        current_h2_id = elem_id
                    else:
                        parent_id = current_h2_id or current_h1_id

                    doc.elements.append(
                        DocumentElement(
                            element_id=elem_id,
                            element_type=ElementType.HEADING,
                            text=title.strip(),
                            level=level,
                            line_start=line_num,
                            line_end=line_num,
                            char_start=char_offset,
                            char_end=char_offset + line_len,
                            parent_heading_id=parent_id,
                        )
                    )
                    char_offset += line_len
                    continue

            # Handle List Items
            if line.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s+", line):
                element_idx += 1
                doc.elements.append(
                    DocumentElement(
                        element_id=f"{file_id}_elem_{element_idx}",
                        element_type=ElementType.LIST_ITEM,
                        text=line,
                        line_start=line_num,
                        line_end=line_num,
                        char_start=char_offset,
                        char_end=char_offset + line_len,
                        parent_heading_id=current_h2_id or current_h1_id,
                    )
                )
                char_offset += line_len
                continue

            # Regular Paragraph
            if line:
                element_idx += 1
                doc.elements.append(
                    DocumentElement(
                        element_id=f"{file_id}_elem_{element_idx}",
                        element_type=ElementType.PARAGRAPH,
                        text=line,
                        line_start=line_num,
                        line_end=line_num,
                        char_start=char_offset,
                        char_end=char_offset + line_len,
                        parent_heading_id=current_h2_id or current_h1_id,
                    )
                )

            char_offset += line_len

        # Flush any trailing table
        if in_table and table_lines:
            self._flush_markdown_table(table_lines, doc, file_id, element_idx, table_start_line, len(lines), table_char_start, char_offset, current_h2_id or current_h1_id)

    def _flush_markdown_table(self, table_lines: List[str], doc: Document, file_id: str, element_idx: int, start_line: int, end_line: int, start_char: int, end_char: int, parent_id: Optional[str]):
        parsed_rows = []
        for tl in table_lines:
            cells = [c.strip() for c in tl.strip("|").split("|")]
            # Filter separator lines like |---|---|
            if all(set(c).issubset({"-", ":", " "}) for c in cells if c):
                continue
            parsed_rows.append(cells)

        if parsed_rows:
            headers = parsed_rows[0]
            rows = parsed_rows[1:] if len(parsed_rows) > 1 else []
            t_data = TableData(headers=headers, rows=rows)
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_{len(doc.elements) + 1}",
                    element_type=ElementType.TABLE,
                    text=t_data.to_markdown(),
                    table_data=t_data,
                    line_start=start_line,
                    line_end=end_line,
                    char_start=start_char,
                    char_end=end_char,
                    parent_heading_id=parent_id,
                )
            )

    def _parse_source_code(self, lines: List[str], doc: Document, file_id: str, ext: str):
        """Extracts functions, classes, and comments from source code."""
        element_idx = 0
        current_class = None
        char_offset = 0
        buffer_lines = []
        buf_start_line = 1
        buf_start_char = 0

        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".rs": "rust", ".go": "go", ".c": "c", ".cpp": "cpp", ".java": "java",
        }
        lang = lang_map.get(ext, "code")

        for line_num, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            line_len = len(raw_line)

            # Detect class / type definitions
            rust_types = (
                "struct ", "pub struct ", "pub(crate) struct ",
                "enum ", "pub enum ", "pub(crate) enum ",
                "impl ", "pub impl ", "pub(crate) impl ",
                "trait ", "pub trait ", "pub(crate) trait ",
            )
            if line.startswith("class ") or ((ext in (".rs", "rust") or lang == "rust") and line.startswith(rust_types)):
                if buffer_lines:
                    element_idx += 1
                    doc.elements.append(
                        DocumentElement(
                            element_id=f"{file_id}_elem_{element_idx}",
                            element_type=ElementType.CODE_BLOCK,
                            text="".join(buffer_lines).strip(),
                            language=lang,
                            line_start=buf_start_line,
                            line_end=line_num - 1,
                            char_start=buf_start_char,
                            char_end=char_offset,
                        )
                    )
                    buffer_lines = []

                element_idx += 1
                elem_id = f"{file_id}_elem_{element_idx}"
                current_class = elem_id
                doc.elements.append(
                    DocumentElement(
                        element_id=elem_id,
                        element_type=ElementType.HEADING,
                        text=line.rstrip(":").rstrip("{").strip(),
                        level=1,
                        line_start=line_num,
                        line_end=line_num,
                        char_start=char_offset,
                        char_end=char_offset + line_len,
                    )
                )
                buf_start_line = line_num + 1
                buf_start_char = char_offset + line_len
                char_offset += line_len
                continue

            # Detect functions
            fn_prefixes = (
                "def ", "async def ", "function ",
                "fn ", "pub fn ", "pub(crate) fn ", "async fn ", "pub async fn ", "pub(crate) async fn ",
                "public void ", "public int ",
            )
            if line.startswith(fn_prefixes):
                if buffer_lines:
                    element_idx += 1
                    doc.elements.append(
                        DocumentElement(
                            element_id=f"{file_id}_elem_{element_idx}",
                            element_type=ElementType.CODE_BLOCK,
                            text="".join(buffer_lines).strip(),
                            language=lang,
                            line_start=buf_start_line,
                            line_end=line_num - 1,
                            char_start=buf_start_char,
                            char_end=char_offset,
                            parent_heading_id=current_class,
                        )
                    )
                    buffer_lines = []

                element_idx += 1
                elem_id = f"{file_id}_elem_{element_idx}"
                doc.elements.append(
                    DocumentElement(
                        element_id=elem_id,
                        element_type=ElementType.HEADING,
                        text=line.rstrip(":").rstrip("{").strip(),
                        level=2,
                        line_start=line_num,
                        line_end=line_num,
                        char_start=char_offset,
                        char_end=char_offset + line_len,
                        parent_heading_id=current_class,
                    )
                )
                buf_start_line = line_num + 1
                buf_start_char = char_offset + line_len
                char_offset += line_len
                continue

            buffer_lines.append(raw_line)
            char_offset += line_len

        if buffer_lines:
            element_idx += 1
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_{element_idx}",
                    element_type=ElementType.CODE_BLOCK,
                    text="".join(buffer_lines).strip(),
                    language=lang,
                    line_start=buf_start_line,
                    line_end=len(lines),
                    char_start=buf_start_char,
                    char_end=char_offset,
                    parent_heading_id=current_class,
                )
            )

    def _parse_plain_text(self, lines: List[str], doc: Document, file_id: str):
        """Splits plain text into paragraphs separated by blank lines."""
        element_idx = 0
        char_offset = 0
        p_lines = []
        p_start_line = 1
        p_start_char = 0

        for line_num, raw_line in enumerate(lines, start=1):
            line_len = len(raw_line)
            line = raw_line.strip()

            if not line:
                if p_lines:
                    element_idx += 1
                    doc.elements.append(
                        DocumentElement(
                            element_id=f"{file_id}_elem_{element_idx}",
                            element_type=ElementType.PARAGRAPH,
                            text="".join(p_lines).strip(),
                            line_start=p_start_line,
                            line_end=line_num - 1,
                            char_start=p_start_char,
                            char_end=char_offset,
                        )
                    )
                    p_lines = []
                p_start_line = line_num + 1
                p_start_char = char_offset + line_len
            else:
                p_lines.append(raw_line)

            char_offset += line_len

        if p_lines:
            element_idx += 1
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_{element_idx}",
                    element_type=ElementType.PARAGRAPH,
                    text="".join(p_lines).strip(),
                    line_start=p_start_line,
                    line_end=len(lines),
                    char_start=p_start_char,
                    char_end=char_offset,
                )
            )
