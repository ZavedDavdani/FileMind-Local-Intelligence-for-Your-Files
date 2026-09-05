# FileMind — Multiformat + Multimodal Intelligence Report

## 1. Executive Summary

This engineering pass transitions **FileMind** from a document-oriented local RAG system into a **multiformat, multimodal knowledge engine** while strictly adhering to local-first privacy, deterministic provenance, bounded memory/compute guarantees, and zero regression across the existing test suite.

FileMind now natively sniffs, parses, indexes, retrieves, and cites grounded knowledge across:
1. **Documents & Rich Markup**: PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, CSV, TSV, TXT, Markdown, JSON, XML, HTML, RTF.
2. **Static & Vector Images**: PNG, JPG/JPEG, WEBP, BMP, TIFF, TIF, ICO, SVG.
3. **Audio Containers**: MP3, WAV, M4A, FLAC, OGG, AAC, WMA.
4. **Video Containers**: MP4, MKV, MOV, AVI, WEBM, WMV.

All formats are treated as disk-authoritative sources of truth, chunked hierarchically with exact boundary preservation, hydrated into SQLite FTS5 and vector indices, and surfaced through rich provenance citations (\sheet_name\, \slide_number\, \	ime_start\, \	ime_end\, \rame_index\, \media_type\, \extraction_method\).

---

## 2. Architecture & Pipeline Enhancements

### 2.1 File Sniffing & Format Detection (\ackend/app/intelligence/detector.py\)
- **MIME & Extension Mapping**: Comprehensive coverage mapping 25+ file extensions to canonical MIME types.
- **Magic-Byte Sniffing**: Resilient header detection identifying ISO MP4/MOV atoms (\typ\, \moov\), Matroska EBML headers, PNG/JPEG/WEBP/GIF signatures, ID3/WAV headers, and OLE2 structured storage.

### 2.2 Normalized Multimodal Data Model (\ackend/app/intelligence/models.py\ & \provenance.py\)
- **New Element Types**: \ElementType.TRANSCRIPT_SEGMENT\, \ElementType.IMAGE_CAPTION\, \ElementType.VISUAL_METADATA\.
- **Extended Provenance**: Added \sheet_name\, \slide_number\, \	ime_start\, \	ime_end\, \rame_index\, \media_type\, \extraction_method\ fields to both \DocumentElement\ and \ChunkProvenance\.

### 2.3 Modular Multiformat & Multimodal Parsers (\ackend/app/intelligence/parsers/\)
- **\image_parser.py\**:
  - Extracts image dimensions, mode, and EXIF camera/device metadata.
  - Pluggable OCR interface (\BaseOCREngine\ with PyMuPDF / pytesseract fallback).
  - Pluggable local vision interface (\BaseVisionEngine\ with Ollama / local vision fallback).
  - Pure XML SVG parser extracting embedded vector titles, descriptions, and text nodes.
- **\udio_parser.py\**:
  - Container header inspection extracting duration, channels, sample rate, and format without heavy subprocesses.
  - Pluggable transcription interface (\BaseTranscriptionEngine\ with Faster-Whisper / OpenAI-Whisper fallback) yielding timestamped transcript segments \[MM:SS - MM:SS]\.
- **\ideo_parser.py\**:
  - Lightweight ISO/Matroska container header parser extracting duration, resolution, and format.
  - Bounded keyframe sampling (<= 10 keyframes per video) preventing runaway resource consumption.
- **\	abular_parser.py\**:
  - Delimited text parser with \csv.Sniffer\ for CSV and TSV.
  - Hierarchical XML tag/attribute tree parser.
  - Nested JSON object and array-of-objects tabular flattener.
  - Multi-sheet Excel workbook parser with bounded row-group chunking (50 rows/chunk with header retention).
- **\pptx_parser.py\**:
  - Presentation slide parser with exact slide number tracking and speaker note extraction.
- **tf_html_parser.py\**:
  - Pure-Python RTF control word decoder.
  - Robust \CleanHTMLParser\ stripping dangerous script, style, head, and nav tags while preserving structural headings and tables.
- **\legacy_doc_ppt_parser.py\**:
  - Safe OLE2 structured storage plain-text stream extractor for legacy \.doc\ and \.ppt\ binary files.
- **egistry.py\**:
  - Lazy-loaded registry mapping every supported MIME type and extension to its dedicated parser.

### 2.4 Hierarchical Chunker & Engine Pipeline
- **\hierarchical.py\**: Media boundary awareness flushes accumulated tokens when encountering transcript segments, image captions, or media transitions.
- **\pipeline.py\**: Central routing dispatching files to their corresponding parsers, enforcing max size thresholds, SHA-256 integrity verification, and non-blocking failure isolation.

### 2.5 Storage, Retrieval & Prompting Grounding
- **\chunks.py\**: Serializes and unpacks multimodal provenance attributes inside SQLite \metadata_json\.
- **\lexical.py\, \ector_store.py\, \hybrid.py\**: Propagate multimodal provenance through BM25, Dense embeddings, RRF, and cross-encoder reranking.
- **\prompt.py\, \context.py\, \sk_service.py\**: Render rich contextual citation headers (e.g., \[recording.mp3 | Timestamp: [00:15 - 00:45] | Media: AUDIO | Method: transcription]\).
- **\schemas.py\ & Frontend UI**: Surface badges and icons for sheet name, slide number, timestamps, keyframe indices, and media types across Search, Ask, and Chunk Inspector modals.

---

## 3. Verification & Test Matrix

| Test Suite | Total Tests | Status | Details |
| :--- | :---: | :---: | :--- |
| Multiformat Parsers (\	est_multiformat_parsers.py\) | 10 | **PASSED** | Format sniffing, CSV/TSV, XML, JSON, HTML, RTF, Legacy OLE2, Registry |
| Multimodal Media (\	est_multimodal_media.py\) | 4 | **PASSED** | Image EXIF/dimensions, SVG XML, Audio WAV headers, Video MP4 atoms |
| Multimodal Retrieval (\	est_multimodal_retrieval.py\) | 4 | **PASSED** | Hierarchical chunker provenance, DB serialization, prompt headers, citations |
| Core Regression Suite (\ackend/tests/\) | 633 | **PASSED** | 633 passed, 1 skipped across all unit, integration, and security tests |
| Frontend Production Build (\rontend/\) | 1 | **PASSED** | \	sc && vite build\ built in 6.83s with 0 errors |
| Tauri Rust Cargo Check (\src-tauri/\) | 1 | **PASSED** | \cargo check\ completed in 4.49s with 0 warnings/errors |

---

## 4. Gate Verdict

**MULTIFORMAT + MULTIMODAL PASS — READY FOR WINDOWS GENERALIZATION**
