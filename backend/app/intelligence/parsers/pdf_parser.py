"""PDF document parsers: PyMuPDF (Primary) and PyPDF (Benchmark candidate)."""

import os
from typing import List, Optional
import fitz  # PyMuPDF
import pypdf

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
    EncryptedDocumentError,
)
from app.intelligence.parsers.quality import (
    analyze_raw_text_signals,
    assess_pdf_quality,
)


class PyMuPDFParser(BaseParser):
    """
    High-performance, layout-aware PDF parser using PyMuPDF (fitz).
    Extracts text blocks, font-size heuristics for headings, tables, and page boundaries,
    preserving top-to-bottom reading order.
    """

    @property
    def parser_name(self) -> str:
        return "pymupdf-parser"

    @property
    def parser_version(self) -> str:
        return "1.0.0"

    @property
    def supported_mime_types(self) -> List[str]:
        return ["application/pdf"]

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "application/pdf") -> Document:
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
            pdf_doc = fitz.open(file_path)
        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to open PDF file: {str(exc)}") from exc

        try:
            if pdf_doc.is_encrypted:
                # Try default empty password
                if not pdf_doc.authenticate(""):
                    raise EncryptedDocumentError(f"PDF is password protected or encrypted: {filename}")

            doc_obj.total_pages = pdf_doc.page_count
            meta = pdf_doc.metadata or {}
            doc_obj.title = meta.get("title") or filename
            doc_obj.metadata = {
                "author": meta.get("author"),
                "creator": meta.get("creator"),
                "producer": meta.get("producer"),
                "page_count": pdf_doc.page_count,
            }

            element_idx = 0
            current_h1_id = None
            current_h2_id = None
            raw_page_texts = []
            total_images = 0

            for page_num in range(1, pdf_doc.page_count + 1):
                page = pdf_doc[page_num - 1]
                page_items = []  # List of tuples: (y0, element_data)

                # Raw page text and image discovery for quality gate
                raw_page_text = page.get_text("text") or ""
                raw_page_texts.append(raw_page_text)
                try:
                    page_images = page.get_images()
                    total_images += len(page_images)
                except Exception:
                    pass

                # 1. Identify Tables
                table_rects = []
                try:
                    tables = page.find_tables()
                    for t in tables:
                        table_rects.append(t.bbox)
                        df_rows = t.extract()
                        if df_rows and len(df_rows) > 0:
                            headers = [str(c or "").strip() for c in df_rows[0]]
                            rows = [[str(c or "").strip() for c in r] for r in df_rows[1:]]
                            t_data = TableData(headers=headers, rows=rows)
                            page_items.append((
                                t.bbox[1],
                                {
                                    "type": ElementType.TABLE,
                                    "text": t_data.to_markdown(),
                                    "table_data": t_data,
                                }
                            ))
                except Exception:
                    pass

                # 2. Extract Text Blocks and infer structure
                page_dict = page.get_text("dict")
                blocks = page_dict.get("blocks", [])

                font_sizes = []
                for b in blocks:
                    if "lines" in b:
                        for l in b["lines"]:
                            for s in l.get("spans", []):
                                if s.get("text", "").strip():
                                    font_sizes.append(s.get("size", 10.0))

                median_font_size = 10.0
                if font_sizes:
                    sorted_sizes = sorted(font_sizes)
                    median_font_size = sorted_sizes[len(sorted_sizes) // 2]

                for b in blocks:
                    if "lines" not in b:
                        continue

                    b_rect = fitz.Rect(b["bbox"])
                    if any(b_rect.intersects(fitz.Rect(tr)) for tr in table_rects):
                        continue

                    block_text_parts = []
                    max_span_size = 0.0
                    is_bold = False

                    for l in b["lines"]:
                        line_text = "".join(s.get("text", "") for s in l.get("spans", []))
                        block_text_parts.append(line_text)
                        for s in l.get("spans", []):
                            size = s.get("size", 0.0)
                            if size > max_span_size:
                                max_span_size = size
                            flags = s.get("flags", 0)
                            if flags & 2 != 0 or "bold" in s.get("font", "").lower():
                                is_bold = True

                    block_text = "\n".join(block_text_parts).strip()
                    if not block_text:
                        continue

                    is_short = len(block_text.splitlines()) <= 3 and len(block_text) < 160
                    if is_short and max_span_size >= median_font_size * 1.35:
                        page_items.append((
                            b["bbox"][1],
                            {
                                "type": ElementType.HEADING,
                                "text": block_text,
                                "level": 1,
                            }
                        ))
                    elif is_short and (max_span_size >= median_font_size * 1.15 or (is_bold and max_span_size >= median_font_size)):
                        page_items.append((
                            b["bbox"][1],
                            {
                                "type": ElementType.HEADING,
                                "text": block_text,
                                "level": 2,
                            }
                        ))
                    elif block_text.startswith(("- ", "• ", "* ", "1. ", "2. ", "3. ")):
                        page_items.append((
                            b["bbox"][1],
                            {
                                "type": ElementType.LIST_ITEM,
                                "text": block_text,
                            }
                        ))
                    else:
                        page_items.append((
                            b["bbox"][1],
                            {
                                "type": ElementType.PARAGRAPH,
                                "text": block_text,
                            }
                        ))

                # Sort elements on this page by vertical top coordinate (y0)
                page_items.sort(key=lambda item: item[0])

                for _, item_data in page_items:
                    element_idx += 1
                    elem_id = f"{file_id}_elem_{element_idx}"
                    e_type = item_data["type"]

                    if e_type == ElementType.HEADING:
                        level = item_data.get("level", 1)
                        if level == 1:
                            elem = DocumentElement(
                                element_id=elem_id,
                                element_type=ElementType.HEADING,
                                text=item_data["text"],
                                page_number=page_num,
                                level=1,
                            )
                            current_h1_id = elem_id
                            current_h2_id = None
                        else:
                            elem = DocumentElement(
                                element_id=elem_id,
                                element_type=ElementType.HEADING,
                                text=item_data["text"],
                                page_number=page_num,
                                level=2,
                                parent_heading_id=current_h1_id,
                            )
                            current_h2_id = elem_id
                    elif e_type == ElementType.TABLE:
                        elem = DocumentElement(
                            element_id=elem_id,
                            element_type=ElementType.TABLE,
                            text=item_data["text"],
                            page_number=page_num,
                            table_data=item_data.get("table_data"),
                            parent_heading_id=current_h2_id or current_h1_id,
                        )
                    elif e_type == ElementType.LIST_ITEM:
                        elem = DocumentElement(
                            element_id=elem_id,
                            element_type=ElementType.LIST_ITEM,
                            text=item_data["text"],
                            page_number=page_num,
                            parent_heading_id=current_h2_id or current_h1_id,
                        )
                    else:
                        elem = DocumentElement(
                            element_id=elem_id,
                            element_type=ElementType.PARAGRAPH,
                            text=item_data["text"],
                            page_number=page_num,
                            parent_heading_id=current_h2_id or current_h1_id,
                        )

                    doc_obj.elements.append(elem)

            # Hardening H3: Assess extraction quality
            full_raw_text = "".join(raw_page_texts)
            signals = analyze_raw_text_signals(
                raw_text=full_raw_text,
                page_texts=raw_page_texts,
                page_count=pdf_doc.page_count,
                image_count=total_images,
            )
            assessment = assess_pdf_quality(signals)
            doc_obj.quality_assessment = assessment
            doc_obj.metadata["quality_assessment"] = assessment.to_dict()

        finally:
            pdf_doc.close()

        return doc_obj


class PyPDFParser(BaseParser):
    """
    Simpler baseline PDF parser using pypdf for benchmarking comparisons.
    Extracts text page-by-page without deep layout / table bounding box analysis.
    """

    @property
    def parser_name(self) -> str:
        return "pypdf-parser"

    @property
    def parser_version(self) -> str:
        return "1.0.0"

    @property
    def supported_mime_types(self) -> List[str]:
        return ["application/pdf"]

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "application/pdf") -> Document:
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
            reader = pypdf.PdfReader(file_path)
        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to read PDF with pypdf: {str(exc)}") from exc

        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
                if not decrypted:
                    raise EncryptedDocumentError(f"PDF is password protected or encrypted: {filename}")
            except EncryptedDocumentError:
                raise
            except Exception as dec_exc:
                raise EncryptedDocumentError(f"PDF is encrypted: {filename} ({dec_exc})") from dec_exc


        doc_obj.total_pages = len(reader.pages)
        element_idx = 0
        raw_page_texts = []
        total_images = 0

        for page_idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            raw_page_texts.append(text)
            try:
                total_images += len(page.images)
            except Exception:
                pass

            paragraphs = text.split("\n\n")
            for p in paragraphs:
                p_str = p.strip()
                if not p_str:
                    continue
                element_idx += 1
                elem = DocumentElement(
                    element_id=f"{file_id}_elem_{element_idx}",
                    element_type=ElementType.PARAGRAPH,
                    text=p_str,
                    page_number=page_idx,
                )
                doc_obj.elements.append(elem)

        # Hardening H3: Assess extraction quality
        full_raw_text = "".join(raw_page_texts)
        signals = analyze_raw_text_signals(
            raw_text=full_raw_text,
            page_texts=raw_page_texts,
            page_count=len(reader.pages),
            image_count=total_images,
        )
        assessment = assess_pdf_quality(signals)
        doc_obj.quality_assessment = assessment
        doc_obj.metadata["quality_assessment"] = assessment.to_dict()

        return doc_obj
