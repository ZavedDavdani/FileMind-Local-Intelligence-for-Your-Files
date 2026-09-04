import csv
import io
import json
import os
from typing import List, Optional
import openpyxl

from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
    TableData,
)
from app.intelligence.parsers.base import BaseParser, CorruptedDocumentError
from app.intelligence.parsers.decoder import read_text_file_strictly



class TabularParser(BaseParser):
    """
    Parser for structured datasets: CSV, JSON, and Microsoft Excel (.xlsx).
    Extracts tabular headers, row data, and worksheet hierarchies.
    """

    @property
    def parser_name(self) -> str:
        return "tabular-parser"

    @property
    def parser_version(self) -> str:
        return "1.0.0"

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "text/csv",
            "application/json",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".csv", ".json", ".xlsx"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "text/csv") -> Document:
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

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
            if ext == ".csv":
                self._parse_csv(file_path, doc_obj, file_id)
            elif ext == ".json":
                self._parse_json(file_path, doc_obj, file_id)
            elif ext == ".xlsx":
                self._parse_xlsx(file_path, doc_obj, file_id)
        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to parse tabular file {filename}: {str(exc)}") from exc

        return doc_obj

    def _parse_csv(self, file_path: str, doc: Document, file_id: str):
        content = read_text_file_strictly(file_path, filename=doc.filename)
        reader = csv.reader(io.StringIO(content))
        rows = [row for row in reader if any(cell.strip() for cell in row)]

        if rows:
            headers = [c.strip() for c in rows[0]]
            data_rows = [[c.strip() for c in r] for r in rows[1:]]
            t_data = TableData(headers=headers, rows=data_rows, caption=doc.filename)
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_1",
                    element_type=ElementType.TABLE,
                    text=t_data.to_markdown(),
                    table_data=t_data,
                    line_start=1,
                    line_end=len(rows),
                )
            )

    def _parse_json(self, file_path: str, doc: Document, file_id: str):
        content = read_text_file_strictly(file_path, filename=doc.filename)
        data = json.loads(content)


        element_idx = 0
        if isinstance(data, list) and data and isinstance(data[0], dict):
            # Array of objects -> Table
            headers = list(data[0].keys())
            rows = [[str(item.get(k, "")) for k in headers] for item in data]
            t_data = TableData(headers=headers, rows=rows, caption=doc.filename)
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_1",
                    element_type=ElementType.TABLE,
                    text=t_data.to_markdown(),
                    table_data=t_data,
                )
            )
        elif isinstance(data, dict):
            for key, val in data.items():
                element_idx += 1
                doc.elements.append(
                    DocumentElement(
                        element_id=f"{file_id}_elem_{element_idx}",
                        element_type=ElementType.HEADING,
                        text=f"Key: {key}",
                        level=2,
                    )
                )
                element_idx += 1
                val_str = json.dumps(val, indent=2) if isinstance(val, (dict, list)) else str(val)
                doc.elements.append(
                    DocumentElement(
                        element_id=f"{file_id}_elem_{element_idx}",
                        element_type=ElementType.PARAGRAPH,
                        text=val_str,
                    )
                )
        else:
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_1",
                    element_type=ElementType.PARAGRAPH,
                    text=json.dumps(data, indent=2),
                )
            )

    def _parse_xlsx(self, file_path: str, doc: Document, file_id: str):
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        try:
            doc.total_pages = len(wb.sheetnames)
            element_idx = 0

            for sheet_idx, sheet_name in enumerate(wb.sheetnames, start=1):
                sheet = wb[sheet_name]
                rows_data = []
                for row in sheet.iter_rows(values_only=True):
                    if any(c is not None and str(c).strip() for c in row):
                        rows_data.append([str(c or "").strip() for c in row])

                if rows_data:
                    element_idx += 1
                    elem_h = DocumentElement(
                        element_id=f"{file_id}_elem_{element_idx}",
                        element_type=ElementType.HEADING,
                        text=f"Worksheet: {sheet_name}",
                        page_number=sheet_idx,
                        level=1,
                    )
                    doc.elements.append(elem_h)

                    headers = rows_data[0]
                    body_rows = rows_data[1:] if len(rows_data) > 1 else []
                    t_data = TableData(headers=headers, rows=body_rows, caption=sheet_name)
                    element_idx += 1
                    elem_t = DocumentElement(
                        element_id=f"{file_id}_elem_{element_idx}",
                        element_type=ElementType.TABLE,
                        text=t_data.to_markdown(),
                        page_number=sheet_idx,
                        table_data=t_data,
                        parent_heading_id=elem_h.element_id,
                        line_start=1,
                        line_end=len(rows_data),
                    )
                    doc.elements.append(elem_t)
        finally:
            wb.close()
