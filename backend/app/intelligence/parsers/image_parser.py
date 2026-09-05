"""Image parser for FileMind Multiformat & Multimodal Intelligence.

Extracts native image metadata, EXIF properties, optional OCR text, and
optional local vision model descriptions with graceful degradation.
"""

import base64
import io
import logging
import os
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
from typing import Any, Dict, List, Optional

from PIL import ExifTags, Image

from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
)
from app.intelligence.parsers.base import BaseParser, CorruptedDocumentError

logger = logging.getLogger("FileMind.Intelligence.Parsers.Image")

IMAGE_PARSER_VERSION = "1.0.0"


class BaseOCREngine:
    """Pluggable OCR interface."""

    def extract_text(self, image_path: str) -> Optional[str]:
        raise NotImplementedError


class LocalOCREngine(BaseOCREngine):
    """Local OCR engine with graceful fallback if external OCR dependencies are missing."""

    def __init__(self):
        self._tesseract_available: Optional[bool] = None

    def extract_text(self, image_path: str) -> Optional[str]:
        # Try pytesseract if available
        try:
            import pytesseract  # type: ignore
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img).strip()
            if text:
                return text
        except Exception:
            pass

        # Try PyMuPDF OCR / text extraction if available
        try:
            import pymupdf  # type: ignore
            doc = pymupdf.open(image_path)
            if len(doc) > 0:
                page = doc[0]
                text = page.get_text().strip()
                if text:
                    return text
        except Exception:
            pass

        return None


class BaseVisionEngine:
    """Pluggable local vision description interface."""

    def describe_image(self, image_path: str, prompt: Optional[str] = None) -> Optional[str]:
        raise NotImplementedError


class LocalVisionEngine(BaseVisionEngine):
    """Local Ollama vision model connector with graceful degradation."""

    def __init__(self, model_name: str = "llava", base_url: str = "http://127.0.0.1:11434"):
        self.model_name = model_name
        self.base_url = base_url

    def describe_image(self, image_path: str, prompt: Optional[str] = None) -> Optional[str]:
        try:
            from app.ai.ollama_provider import OllamaProvider
            if not os.path.exists(image_path) or os.path.getsize(image_path) > 20 * 1024 * 1024:
                return None

            with Image.open(image_path) as img:
                max_dim = 1024
                if max(img.size) > max_dim:
                    img.thumbnail((max_dim, max_dim))
                buffered = io.BytesIO()
                img_format = "PNG" if img.format == "PNG" else "JPEG"
                img.convert("RGB").save(buffered, format=img_format)
                b64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

            provider = OllamaProvider(
                base_url=self.base_url,
                model=self.model_name,
                connect_timeout=2.0,
                read_timeout=30.0,
            )
            query = prompt or "Provide a concise, factual description of the visible contents, objects, diagram components, or text in this image."
            resp = provider.generate(prompt=query, options={"temperature": 0.1})
            return resp.response.strip() if resp and resp.response else None
        except Exception as exc:
            logger.debug("Vision extraction skipped for %s: %s", image_path, exc)
            return None


class ImageParser(BaseParser):
    """Parser for static raster and vector images (.png, .jpg, .jpeg, .webp, .bmp, .tiff, .tif, .ico, .svg)."""

    def __init__(
        self,
        ocr_engine: Optional[BaseOCREngine] = None,
        vision_engine: Optional[BaseVisionEngine] = None,
    ):
        self.ocr_engine = ocr_engine or LocalOCREngine()
        self.vision_engine = vision_engine or LocalVisionEngine()

    @property
    def parser_name(self) -> str:
        return "image-parser"

    @property
    def parser_version(self) -> str:
        return IMAGE_PARSER_VERSION

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/bmp",
            "image/tiff",
            "image/x-icon",
            "image/svg+xml",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".ico", ".svg"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "image/png") -> Document:
        file_path = str(file_path)
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
            if ext == ".svg":
                self._parse_svg(file_path, doc_obj, file_id)
            else:
                self._parse_raster_image(file_path, doc_obj, file_id, ext)
        except Exception as exc:
            if isinstance(exc, CorruptedDocumentError):
                raise
            raise CorruptedDocumentError(f"Failed to parse image {filename}: {str(exc)}") from exc

        return doc_obj

    def _parse_svg(self, file_path: str, doc: Document, file_id: str):
        """Extracts text, titles, descriptions, and structure from SVG vector images."""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            texts = []
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if elem.text and elem.text.strip():
                    texts.append(f"{tag}: {elem.text.strip()}")
                if elem.tail and elem.tail.strip():
                    texts.append(elem.tail.strip())

            svg_text = "\n".join(texts) if texts else "SVG Vector Graphic (No embedded text labels)"
            metadata_text = f"Vector Graphic (SVG)\n{svg_text}"

            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_1",
                    element_type=ElementType.VISUAL_METADATA,
                    text=metadata_text,
                    media_type="image",
                    extraction_method="native",
                    metadata={"format": "SVG", "is_vector": True},
                )
            )
        except Exception as exc:
            raise CorruptedDocumentError(f"Malformed SVG XML: {exc}") from exc

    def _parse_raster_image(self, file_path: str, doc: Document, file_id: str, ext: str):
        """Extracts native dimensions, EXIF properties, OCR text, and vision descriptions."""
        try:
            with Image.open(file_path) as img:
                width, height = img.size
                img_format = img.format or ext.lstrip(".").upper()
                mode = img.mode

                exif_data: Dict[str, Any] = {}
                raw_exif = getattr(img, "_getexif", None)
                if raw_exif and callable(raw_exif):
                    exif_dict = raw_exif()
                    if exif_dict and isinstance(exif_dict, dict):
                        for tag_id, value in exif_dict.items():
                            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                            if isinstance(value, (str, int, float)):
                                exif_data[tag_name] = value
                            elif isinstance(value, bytes):
                                try:
                                    exif_data[tag_name] = value.decode("utf-8", errors="ignore").strip("\x00")
                                except Exception:
                                    pass
        except Exception as exc:
            raise CorruptedDocumentError(f"Corrupted image stream: {exc}") from exc

        # 1. Native Metadata Element
        meta_lines = [
            f"Image File: {doc.filename}",
            f"Format: {img_format}",
            f"Dimensions: {width} x {height} pixels",
            f"Color Mode: {mode}",
        ]
        if "DateTime" in exif_data:
            meta_lines.append(f"Date Taken: {exif_data['DateTime']}")
        if "Make" in exif_data or "Model" in exif_data:
            camera = f"{exif_data.get('Make', '')} {exif_data.get('Model', '')}".strip()
            meta_lines.append(f"Camera/Device: {camera}")
        if "ImageDescription" in exif_data:
            meta_lines.append(f"EXIF Description: {exif_data['ImageDescription']}")

        meta_text = "\n".join(meta_lines)
        doc.elements.append(
            DocumentElement(
                element_id=f"{file_id}_elem_1",
                element_type=ElementType.VISUAL_METADATA,
                text=meta_text,
                media_type="image",
                extraction_method="metadata",
                metadata={
                    "width": width,
                    "height": height,
                    "format": img_format,
                    "mode": mode,
                    "exif": exif_data,
                },
            )
        )

        elem_idx = 1

        # 2. OCR Text Extraction (if available)
        ocr_text = self.ocr_engine.extract_text(file_path) if self.ocr_engine else None
        if ocr_text:
            elem_idx += 1
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_{elem_idx}",
                    element_type=ElementType.PARAGRAPH,
                    text=f"[OCR Extracted Text]\n{ocr_text}",
                    media_type="image",
                    extraction_method="ocr",
                    metadata={"has_ocr": True},
                )
            )

        # 3. Optional Local Vision Description (if available)
        vision_desc = self.vision_engine.describe_image(file_path) if self.vision_engine else None
        if vision_desc:
            elem_idx += 1
            doc.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_{elem_idx}",
                    element_type=ElementType.IMAGE_CAPTION,
                    text=f"[Visual Description]\n{vision_desc}",
                    media_type="image",
                    extraction_method="vision_description",
                    metadata={"has_vision_description": True},
                )
            )
