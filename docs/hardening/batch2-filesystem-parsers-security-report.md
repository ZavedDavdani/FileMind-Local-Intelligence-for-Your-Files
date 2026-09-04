# FileMind — Batch 2: Filesystem, Parsers & Security Hardening Report

**Status**: COMPLETE / VERIFIED PASS  
**Branch**: `main`  
**Current Baseline**: 473 passed, 1 skipped (0 failed)  
**Date**: September 2026  

---

## 1. Executive Summary

FileMind has completed **Batch 2 — Filesystem, Parsers & Security Hardening**, conducting an exhaustive audit and targeted fixes across parser and content integrity, filesystem engine safety, and security boundaries.

Key hardening achievements in Batch 2:
1. **Parser & Content Integrity**:
   - **Markdown Code Block Preservation**: Fixed unclosed markdown code fences at EOF in `TextParser._parse_markdown` to flush trailing `CODE_BLOCK` content rather than silently dropping code at end of file.
   - **Go Structural Parsing**: Added structural detection in `TextParser._parse_source_code` for Go types/structs (`type ... struct/interface`) and functions/methods (`func ...`).
   - **Parser Registry Instance Caching**: Fixed `ParserRegistry` to replace all registered extensions/mimetypes sharing the same parser factory with the singleton instance upon first instantiation, preventing redundant instantiations across `.hpp`, `.toml`, `.sql`, etc.
   - **PPTX Speaker Notes**: Added speaker note extraction in `PptxParser` (`slide.has_notes_slide` -> `notes_text_frame.text` -> `Speaker Notes:` paragraph elements).
   - **XLSX Provenance & Resource Safety**: Added explicit line numbers (`line_start=1`, `line_end=len(rows)`) for XLSX table elements and wrapped `openpyxl` workbook handling in `try...finally: wb.close()`.
   - **Header File Format Detection**: Extended `detector.py` to identify `.h` and `.hpp` as `Format.CODE`.
2. **Filesystem Engine & Security Boundaries**:
   - **Windows Explorer Path Quoting**: Wrapped Explorer `/select` targets in quotes `f'/select,"{target_path}"'` to safely handle paths containing spaces, commas, and special characters.
   - **Linux Subprocess Safety**: Added `close_fds=True` to `xdg-open` subprocess execution in `backend/app/main.py`.
   - **Bounded Filesystem Enumeration**: Enforced `MAX_ENUMERATE_LIMIT = 10000` on `/fs/enumerate` to protect against unbounded memory consumption on oversized directories.
   - **Path Traversal & Root Containment**: Verified strict `is_path_within_root` validation and symlink/junction reparse point rejection across all registered folder paths.

---

## 2. Master 115-Item Audit Matrix (Batch 2 Status)

Below is the consolidated status across the 115 tracked audit and backlog items:

| Category | Total Items | Already Fixed | Batch 1 Fixed | Batch 2 Fixed | Not Reproducible / Overlap |
|---|---|---|---|---|---|
| **Thread & Resource Lifecycle** | 18 | 15 | 2 | 0 | 1 |
| **Ollama & Generation Concurrency** | 16 | 14 | 1 | 0 | 1 |
| **Database, WAL & FK Cascades** | 22 | 20 | 1 | 0 | 1 |
| **Retrieval, FTS5 & Vector Store** | 24 | 22 | 0 | 0 | 2 |
| **Filesystem, Parsers & Security** | 18 | 11 | 0 | 6 | 1 |
| **Citation, Provenance & Formatting** | 17 | 15 | 1 | 0 | 1 |
| **Total Tracked** | **115** | **97** | **5** | **6** | **7** |

---

## 3. Detailed Audit of Batch 2 Areas

### A. Parser & Content Integrity
- **Unclosed Markdown Code Fence** (`NEWLY FIXED`): `TextParser._parse_markdown` in [`backend/app/intelligence/parsers/text_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/text_parser.py) now detects if `in_code_block` is `True` when file iteration finishes, flushing the code lines as an explicit `CODE_BLOCK` element.
- **Go Structural Parsing** (`NEWLY FIXED`): `TextParser._parse_source_code` identifies Go function declarations (`func `, `func (`) and type declarations (`type Name struct/interface`) as structural headings for hierarchical chunking.
- **Parser Registry Factory Sharing** (`NEWLY FIXED`): `ParserRegistry.get_parser_for_file` and `list_registered_parsers` in [`backend/app/intelligence/parsers/registry.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/registry.py) update all extension/MIME dictionary mappings pointing to the same factory upon first resolution.
- **PPTX Speaker Notes** (`NEWLY FIXED`): `PptxParser` in [`backend/app/intelligence/parsers/pptx_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/pptx_parser.py) extracts notes text from slide notes slides when present, tagging them as `Speaker Notes: ...` paragraphs.
- **XLSX Line Numbers & Workbook Closure** (`NEWLY FIXED`): `TabularParser._parse_xlsx` in [`backend/app/intelligence/parsers/tabular_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/tabular_parser.py) attaches `line_start=1` and `line_end=len(rows_data)` to table elements and guarantees `wb.close()` in a `finally` block.
- **C/C++ Header Detection** (`NEWLY FIXED`): `detector.py` maps `.h` and `.hpp` extensions to `Format.CODE`.

### B. Filesystem Safety & Security Boundaries
- **Explorer Comma Quoting** (`NEWLY FIXED`): `backend/app/main.py` formats the Windows explorer command as `explorer.exe /select,"{target_path}"`, preventing argument splitting on paths with commas.
- **Process Spawning Sanitization** (`NEWLY FIXED`): Linux `xdg-open` invocation passes `close_fds=True`.
- **Enumeration Cap** (`NEWLY FIXED`): `/fs/enumerate` caps item results at 10,000 entries.
- **Path Containment & Reparse Points** (`ALREADY VERIFIED`): `is_path_within_root` and `is_reparse_point_or_symlink` in `backend/app/engine/path_safety.py` and `scanner.py` protect all scanner and file operations from path traversal and symlink loops.

---

## 4. Test Verification Results

- **Batch 2 Targeted Regression Suite**: 5 / 5 PASS ([`backend/tests/test_hardening_batch2_parsers_security.py`](file:///c:/dev/FileMind/backend/tests/test_hardening_batch2_parsers_security.py))
- **Phase 5 / 5.5 AI & Hardening Suites**: 147 / 147 PASS
- **Full Backend Regression Suite**: **473 passed, 1 skipped** in 280.87s
- **Frontend Production Build**: **PASS** (1,606 modules compiled, `tsc && vite build`)
- **Tauri Desktop Verification**: **PASS** (`cargo check` with 0 errors)
- **Git Whitespace & Formatting**: **PASS** (`git diff --check` clean)
