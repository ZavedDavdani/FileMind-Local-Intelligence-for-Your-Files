"""Format detection and MIME resolution for documents."""

import mimetypes
import os
from typing import Optional, Tuple

# Initialize mimetypes
mimetypes.init()

EXTENSION_MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".py": "text/x-python",
    ".js": "application/javascript",
    ".ts": "application/typescript",
    ".tsx": "text/typescript-jsx",
    ".jsx": "text/javascript-jsx",
    ".rs": "text/x-rust",
    ".go": "text/x-go",
    ".c": "text/x-c",
    ".cpp": "text/x-c++",
    ".h": "text/x-c-header",
    ".java": "text/x-java",
    ".html": "text/html",
    ".css": "text/css",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".xml": "application/xml",
    ".log": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

SUPPORTED_DOCUMENT_EXTENSIONS = set(EXTENSION_MIME_MAP.keys())


def detect_file_format(file_path: str) -> Tuple[str, str]:
    """
    Detects the MIME type and normalized format name of a file.
    Uses extension matching backed by header magic-byte verification.
    
    Returns: (mime_type, format_name)
    """
    ext = os.path.splitext(file_path)[1].lower()
    mime = EXTENSION_MIME_MAP.get(ext)

    if not mime:
        mime, _ = mimetypes.guess_type(file_path)
        if not mime:
            mime = "application/octet-stream"

    # Sniff magic bytes where appropriate
    if os.path.exists(file_path) and os.path.getsize(file_path) >= 4:
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)
                if header.startswith(b"%PDF-"):
                    mime = "application/pdf"
                elif header.startswith(b"PK\x03\x04"):
                    # ZIP container (could be docx, pptx, xlsx)
                    if ext in (".docx", ".pptx", ".xlsx"):
                        mime = EXTENSION_MIME_MAP[ext]
        except Exception:
            pass

    # Normalize format label
    if mime == "application/pdf":
        fmt = "PDF"
    elif "wordprocessingml" in mime or ext == ".docx":
        fmt = "DOCX"
    elif "presentationml" in mime or ext == ".pptx":
        fmt = "PPTX"
    elif "spreadsheetml" in mime or ext == ".xlsx":
        fmt = "XLSX"
    elif ext in (".md", ".markdown") or mime == "text/markdown":
        fmt = "MARKDOWN"
    elif ext == ".csv" or mime == "text/csv":
        fmt = "CSV"
    elif ext == ".json" or mime == "application/json":
        fmt = "JSON"
    elif ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".c", ".cpp", ".java", ".html", ".css", ".yaml", ".yml", ".xml"):
        fmt = "CODE"
    elif mime.startswith("text/") or ext in (".txt", ".log"):
        fmt = "TEXT"
    elif mime.startswith("image/"):
        fmt = "IMAGE"
    else:
        fmt = "UNKNOWN"

    return mime, fmt


def is_supported_document(file_path: str) -> bool:
    """Checks whether the file has a supported document parser."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_DOCUMENT_EXTENSIONS
