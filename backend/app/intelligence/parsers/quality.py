"""
PDF Extraction-Quality Gate & Observability (Hardening H3)

Collects observable extraction signals during PDF parsing (raw characters, printable ratio,
Unicode replacement characters, suspicious control characters, page text density, image presence),
and classifies extraction quality into structured states:
- PARSED: Normal valid content (chunk, embed, vector index).
- PARSE_WARNING: Usable content with minor anomalies (chunk, embed, vector index, record warning).
- REQUIRES_OCR: Scanned image-only, empty, or unparseable font encoding (block vectorization, retain record).
- FAILED_PARSE: Corrupted or unreadable PDF.
"""

from dataclasses import asdict, dataclass, field
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("FileMind.PDFQuality")


@dataclass
class PDFQualitySignals:
    """Independent observable extraction signals measured directly from raw parser output."""
    raw_char_count: int = 0
    printable_char_count: int = 0
    printable_ratio: float = 1.0
    replacement_char_count: int = 0
    replacement_ratio: float = 0.0
    control_char_count: int = 0
    control_char_ratio: float = 0.0
    whitespace_char_count: int = 0
    whitespace_ratio: float = 0.0
    word_count: int = 0
    page_count: int = 0
    pages_with_meaningful_text: int = 0
    image_count: int = 0
    has_images: bool = False
    parser_warnings: List[str] = field(default_factory=list)


@dataclass
class PDFQualityAssessment:
    """Structured quality assessment outcome and diagnostic metadata."""
    status: str  # "PARSED", "PARSE_WARNING", "REQUIRES_OCR", "FAILED_PARSE"
    reason_codes: List[str] = field(default_factory=list)
    signals: PDFQualitySignals = field(default_factory=PDFQualitySignals)
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": self.reason_codes,
            "message": self.message,
            "signals": asdict(self.signals),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


def analyze_raw_text_signals(
    raw_text: str,
    page_texts: List[str],
    page_count: int,
    image_count: int = 0,
    parser_warnings: Optional[List[str]] = None
) -> PDFQualitySignals:
    """
    Computes extraction quality signals from raw extracted text and page distributions.
    All character counts are based on Unicode codepoints before normalization.
    """
    raw_char_count = len(raw_text)
    if raw_char_count == 0:
        return PDFQualitySignals(
            raw_char_count=0,
            printable_char_count=0,
            printable_ratio=0.0,
            replacement_char_count=0,
            replacement_ratio=0.0,
            control_char_count=0,
            control_char_ratio=0.0,
            whitespace_char_count=0,
            whitespace_ratio=0.0,
            word_count=0,
            page_count=page_count,
            pages_with_meaningful_text=0,
            image_count=image_count,
            has_images=(image_count > 0),
            parser_warnings=parser_warnings or [],
        )

    printable_count = 0
    replacement_count = 0
    control_count = 0
    whitespace_count = 0

    for char in raw_text:
        cp = ord(char)
        if char == "\ufffd":
            replacement_count += 1
        elif (cp < 32 and char not in "\n\r\t") or (127 <= cp < 160):
            control_count += 1
        elif char.isspace():
            whitespace_count += 1
            printable_count += 1
        elif char.isprintable():
            printable_count += 1

    words = raw_text.split()
    word_count = len(words)

    meaningful_pages = 0
    for p_text in page_texts:
        cleaned_page = p_text.strip()
        # A page has meaningful text if it has at least 30 characters and 5 words
        if len(cleaned_page) >= 30 and len(cleaned_page.split()) >= 5:
            meaningful_pages += 1

    return PDFQualitySignals(
        raw_char_count=raw_char_count,
        printable_char_count=printable_count,
        printable_ratio=round(printable_count / max(1, raw_char_count), 4),
        replacement_char_count=replacement_count,
        replacement_ratio=round(replacement_count / max(1, raw_char_count), 4),
        control_char_count=control_count,
        control_char_ratio=round(control_count / max(1, raw_char_count), 4),
        whitespace_char_count=whitespace_count,
        whitespace_ratio=round(whitespace_count / max(1, raw_char_count), 4),
        word_count=word_count,
        page_count=page_count,
        pages_with_meaningful_text=meaningful_pages,
        image_count=image_count,
        has_images=(image_count > 0),
        parser_warnings=parser_warnings or [],
    )


def assess_pdf_quality(signals: PDFQualitySignals) -> PDFQualityAssessment:
    """
    Evaluates extraction quality signals using a conservative, explainable decision policy.
    Never rejects valid source code, mathematical notation, tables, or foreign languages.
    """
    reason_codes = []
    
    # Rule 1: Empty or Zero-Extraction Document
    if signals.raw_char_count == 0:
        if signals.has_images:
            reason_codes.append("SCANNED_IMAGE_ONLY")
            reason_codes.append("NO_EXTRACTABLE_TEXT")
            return PDFQualityAssessment(
                status="REQUIRES_OCR",
                reason_codes=reason_codes,
                signals=signals,
                message="PDF contains images but no extractable text. Requires OCR.",
            )
        else:
            reason_codes.append("NO_EXTRACTABLE_TEXT")
            return PDFQualityAssessment(
                status="REQUIRES_OCR",
                reason_codes=reason_codes,
                signals=signals,
                message="PDF contains no extractable text or content.",
            )

    # Rule 2: Scanned Multi-Page / Low-Text with Images
    # If document has pages but zero meaningful text pages, low character count, and contains images
    avg_chars_per_page = signals.raw_char_count / max(1, signals.page_count)
    if signals.pages_with_meaningful_text == 0 and avg_chars_per_page < 25 and signals.has_images:
        reason_codes.append("SCANNED_IMAGE_ONLY")
        reason_codes.append("INSUFFICIENT_EXTRACTABLE_TEXT")
        return PDFQualityAssessment(
            status="REQUIRES_OCR",
            reason_codes=reason_codes,
            signals=signals,
            message="Extracted text is insufficient (< 25 chars/page) and document contains images. Requires OCR.",
        )

    # Rule 3: Severe Font Encoding / Glyph Corruption
    # If over 40% of extracted characters are replacement characters (\uFFFD)
    if signals.raw_char_count >= 30 and signals.replacement_ratio >= 0.40:
        reason_codes.append("CORRUPTED_FONT_ENCODING")
        reason_codes.append("EXCESSIVE_REPLACEMENT_CHARACTERS")
        return PDFQualityAssessment(
            status="REQUIRES_OCR",
            reason_codes=reason_codes,
            signals=signals,
            message="Severe font encoding corruption (>= 40% replacement characters). Requires OCR or clean source.",
        )

    # Rule 4: Moderate Anomalies (PARSE_WARNING - Document continues to indexing)
    warnings = []
    if signals.page_count > 1 and signals.pages_with_meaningful_text > 0 and signals.pages_with_meaningful_text < signals.page_count and signals.has_images:
        warnings.append("PARTIAL_IMAGE_PAGES")

    if signals.raw_char_count >= 30 and 0.05 <= signals.replacement_ratio < 0.40:
        warnings.append("MODERATE_REPLACEMENT_CHARACTERS")

    if signals.raw_char_count >= 30 and signals.control_char_ratio > 0.05:
        warnings.append("SUSPICIOUS_CONTROL_CHARACTERS")

    if signals.page_count == 1 and 1 <= signals.raw_char_count < 30 and not signals.has_images:
        warnings.append("VERY_SHORT_TEXT")

    if warnings:
        return PDFQualityAssessment(
            status="PARSE_WARNING",
            reason_codes=warnings,
            signals=signals,
            message="Document parsed with warnings. Content indexed normally.",
        )

    # Rule 5: Normal Valid Content
    return PDFQualityAssessment(
        status="PARSED",
        reason_codes=["CLEAN_EXTRACTION"],
        signals=signals,
        message="Document extraction passed all quality checks.",
    )
