"""DOCX document parser using python-docx."""

import os
from typing import List, Optional
import docx

from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
    TableData,
)
from app.intelligence.parsers.base import (
    BaseParser,
    CorruptedDocumentError,
    DocumentParserError,
)


class DocxParser(BaseParser):
    """
    Parser for Microsoft Word (.docx) documents.
    Extracts styled headings (Heading 1, Heading 2), paragraphs, bullet lists, and tables.
    """

    @property
    def parser_name(self) -> str:
        return "docx-parser"

    @property
    def parser_version(self) -> str:
        return "1.0.0"

    @property
    def supported_mime_types(self) -> List[str]:
        return ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]

    @property
    def supported_extensions(self) -> List[str]:
        return [".docx"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document") -> Document:
        filename = os.path.basename(file_path)
        doc_obj = Document(
            file_id=file_id,
            source_path=file_path,
            filename=filename,
            mime_type=mime_type,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
        )

        try:
            docx_file = docx.Document(file_path)
        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to open DOCX file: {str(exc)}") from exc

        # Extract core metadata if available
        try:
            core_props = docx_file.core_properties
            doc_obj.title = core_props.title or filename
            doc_obj.metadata = {
                "author": core_props.author,
                "created": str(core_props.created) if core_props.created else None,
                "modified": str(core_props.modified) if core_props.modified else None,
            }
        except Exception:
            doc_obj.title = filename

        element_idx = 0
        current_h1_id = None
        current_h2_id = None

        # Iterate document body elements (paragraphs and tables)
        for child in docx_file.element.body:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag == "p":
                # Paragraph
                p = docx.text.paragraph.Paragraph(child, docx_file)
                text = p.text.strip()
                if not text:
                    continue

                style_name = p.style.name if p.style else ""
                element_idx += 1
                elem_id = f"{file_id}_elem_{element_idx}"

                if "Heading 1" in style_name or "Title" in style_name:
                    elem = DocumentElement(
                        element_id=elem_id,
                        element_type=ElementType.HEADING,
                        text=text,
                        level=1,
                    )
                    current_h1_id = elem_id
                    current_h2_id = None
                elif "Heading 2" in style_name or "Subtitle" in style_name:
                    elem = DocumentElement(
                        element_id=elem_id,
                        element_type=ElementType.HEADING,
                        text=text,
                        level=2,
                        parent_heading_id=current_h1_id,
                    )
                    current_h2_id = elem_id
                elif "Heading 3" in style_name:
                    elem = DocumentElement(
                        element_id=elem_id,
                        element_type=ElementType.HEADING,
                        text=text,
                        level=3,
                        parent_heading_id=current_h2_id or current_h1_id,
                    )
                elif "List" in style_name or "Bullet" in style_name:
                    elem = DocumentElement(
                        element_id=elem_id,
                        element_type=ElementType.LIST_ITEM,
                        text=text,
                        parent_heading_id=current_h2_id or current_h1_id,
                    )
                else:
                    elem = DocumentElement(
                        element_id=elem_id,
                        element_type=ElementType.PARAGRAPH,
                        text=text,
                        parent_heading_id=current_h2_id or current_h1_id,
                    )

                doc_obj.elements.append(elem)

            elif tag == "tbl":
                # Table
                t = docx.table.Table(child, docx_file)
                rows_data = []
                for row in t.rows:
                    rows_data.append([cell.text.strip() for cell in row.cells])

                if rows_data:
                    headers = rows_data[0]
                    rows = rows_data[1:] if len(rows_data) > 1 else []
                    t_data = TableData(headers=headers, rows=rows)
                    element_idx += 1
                    elem = DocumentElement(
                        element_id=f"{file_id}_elem_{element_idx}",
                        element_type=ElementType.TABLE,
                        text=t_data.to_markdown(),
                        table_data=t_data,
                        parent_heading_id=current_h2_id or current_h1_id,
                    )
                    doc_obj.elements.append(elem)

        return doc_obj
