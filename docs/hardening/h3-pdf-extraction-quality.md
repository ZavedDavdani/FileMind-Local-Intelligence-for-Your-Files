# Hardening 3 (H3): PDF Extraction-Quality Gate & Observability

**Authoritative Specification**: `FileMind_Spec_and_Pipeline.pdf`  
**Status**: **COMPLETE / PASS**  
**Audit Timestamp**: 2026-08-30T12:30:00Z  
**Results Artifact**: `docs/hardening/h3-results.json`  

---

## 1. Executive Summary & Verification Matrix

Hardening Task H3 implements a lightweight, conservative extraction-quality gate and observability layer for PDF documents within FileMind's Document Intelligence pipeline. When PyMuPDF encounters image-only scanned PDFs, severely corrupted font mappings, or documents with essentially zero extractable text, naive ingestion previously caused the generation of meaningless chunks, empty embeddings, and vector store poisoning.

The H3 quality gate intercepts parsed documents immediately after PyMuPDF extraction, evaluates independent observable quality signals, classifies the document into explainable outcomes (`PARSED`, `PARSE_WARNING`, `REQUIRES_OCR`, `FAILED_PARSE`), and enforces a strict vectorization boundary blocking `REQUIRES_OCR` files from generating chunks or vector embeddings while retaining full observability in SQLite.

```
+-----------------------------------------------------------------------------+
|                               H3 VERIFICATION MATRIX                        |
+------------------------------------+---------------+------------------------+
| Requirement / Metric               | Target / Gate | Measured Outcome       |
+------------------------------------+---------------+------------------------+
| Independent Quality Signals        | 8+ Signals    | 12 Signals Collected   |
| Explainable Classification Policy  | Conservative  | PASS (0 Weighted Sums) |
| Valid Technical Documents Retained | 0 False Rej.  | 0 False Positives (0%) |
| Scanned / Image-Only PDFs Detected | 100% Detected | 2 / 2 Detected (100%)  |
| Vector Poisoning Prevention        | Zero Vectors  | 0 Chunks, 0 Vectors    |
| Vector Indexing for Valid Content  | Normal Chunks | 100% Vector Indexed    |
| Reprocessing Transition Path       | Auto Recovery | REQUIRES_OCR -> INDEXED|
| Delete Cleanup Integrity           | Clean Purge   | 100% Clean Purge       |
| Performance Overhead per Document  | < 20 ms / doc | 8.95 ms median / doc   |
| Full Pytest Backend Regression     | 100% Pass     | 97 / 97 PASS (100%)    |
| No OCR Implemented (Deferred)      | Zero OCR Code | Confirmed (No OCR)     |
| Phase 4+ Not Authorized            | Strict Bound  | Confirmed (No Phase 4) |
+------------------------------------+---------------+------------------------+
```

---

## 2. Extraction Quality Signals & Calculation Definitions

All signals are computed directly from raw parser output before text stripping or normalization:

1. `raw_char_count`: Total Unicode character codepoints extracted across all pages.
2. `printable_char_count`: Count of characters where `c.isprintable() or c.isspace()`.
3. `printable_ratio`: `printable_char_count / max(1, raw_char_count)`.
4. `replacement_char_count`: Count of Unicode replacement characters `\uFFFD` (indicates font CID/ToUnicode mapping failure).
5. `replacement_ratio`: `replacement_char_count / max(1, raw_char_count)`.
6. `control_char_count`: Count of non-printable control characters `(ord(c) < 32 and c not in '\n\r\t') or (127 <= ord(c) < 160)`.
7. `control_char_ratio`: `control_char_count / max(1, raw_char_count)`.
8. `whitespace_char_count`: Count of whitespace characters (`c.isspace()`).
9. `whitespace_ratio`: `whitespace_char_count / max(1, raw_char_count)`.
10. `word_count`: Count of space-delimited text tokens.
11. `page_count`: Total page count reported by PyMuPDF (`doc.page_count`).
12. `pages_with_meaningful_text`: Number of pages with $\ge 30$ characters and $\ge 5$ words.
13. `image_count`: Total image XObjects detected across pages via `page.get_images()`.

---

## 3. Classification Outcomes & Conservative Decision Rules

The decision logic enforces explainability without weighted scoring heuristics:

### A. `REQUIRES_OCR` (Vectorization Blocked)
1. **Empty Document**: `page_count > 0` and `raw_char_count == 0`.
   - Reason: `["NO_EXTRACTABLE_TEXT"]` (plus `["SCANNED_IMAGE_ONLY"]` if `image_count > 0`).
2. **Scanned Image-Only / Stamp-Only**: `page_count >= 1`, `pages_with_meaningful_text == 0`, average characters per page $< 25$, and `has_images == True`.
   - Reason: `["SCANNED_IMAGE_ONLY", "INSUFFICIENT_EXTRACTABLE_TEXT"]`.
3. **Severe Font Corruption**: `raw_char_count >= 30` and `replacement_ratio >= 0.40`.
   - Reason: `["CORRUPTED_FONT_ENCODING", "EXCESSIVE_REPLACEMENT_CHARACTERS"]`.

### B. `PARSE_WARNING` (Content Indexed Normally + Diagnostic Warning)
1. **Partial Image Pages**: Multi-page document with valid text pages alongside pure image/diagram pages (`pages_with_meaningful_text < page_count` and `has_images == True`).
   - Reason: `["PARTIAL_IMAGE_PAGES"]`.
2. **Moderate Replacement Glyphs**: `0.05 <= replacement_ratio < 0.40`.
   - Reason: `["MODERATE_REPLACEMENT_CHARACTERS"]`.
3. **Suspicious Control Characters**: `control_char_ratio > 0.05`.
   - Reason: `["SUSPICIOUS_CONTROL_CHARACTERS"]`.
4. **Very Short Text**: Single-page text $< 30$ characters without images.
   - Reason: `["VERY_SHORT_TEXT"]`.

### C. `PARSED` (Normal Indexing)
- All documents with meaningful text density ($\ge 30$ characters or $\ge 1$ meaningful page), `printable_ratio >= 0.85`, and `replacement_ratio < 0.05`.

---

## 4. Vectorization Boundary & Poisoning Prevention

When `WorkerPool` encounters a document classified as `REQUIRES_OCR`:
1. `repo.delete_chunks_by_file(file_id)` purges any preexisting chunks.
2. `vec_store.delete_by_file_id(file_id)` deletes any preexisting vector embeddings from the `chunk_vectors` table.
3. The file record is updated to `index_status = 'SKIPPED'` with structured JSON diagnostic metadata stored in `files.indexing_error`.
4. The indexing job completes with `COMPLETED` and records the SHA-256 hash.
5. **No chunks are inserted, no embeddings are calculated, and zero vectors are written.**

---

## 5. Benchmark Performance & Evaluation Telemetry

Across a 10-document synthetic evaluation corpus across 5 independent runs:
- **Total Corpus Latency (Median)**: **89.50 ms** (Range: 73.32 ms – 103.10 ms)
- **Average Latency per Document (Median)**: **8.95 ms** (Range: 7.33 ms – 10.31 ms)
- **Evaluated Documents**: 10
  - `PARSED`: 7 (Normal text, Multi-page report, Source code, Mathematics, Dense table, Multilingual Unicode, Short invoice)
  - `PARSE_WARNING`: 1 (Partial image diagram)
  - `REQUIRES_OCR`: 2 (Scanned image-only, Scanned with header stamp)
  - `FAILED_PARSE`: 0
- **False Positives**: **0** (0.0% — Valid code, math, foreign language, and short documents were 100% preserved)
- **False Negatives**: **0** (0.0% — Scanned documents were 100% caught)
- **Vector Poisoning Prevented Documents**: **2**

---

## 6. Full Test Suite Regression

- **Backend Pytest Suite**: **97 / 97 unit & integration tests passing (100%)** (`pytest tests/ -v`).
- **New Test File**: `backend/tests/test_pdf_quality_gate.py` (12 test scenarios).
- **Benchmark Runner**: `backend/tests/benchmark_pdf_quality.py`.
