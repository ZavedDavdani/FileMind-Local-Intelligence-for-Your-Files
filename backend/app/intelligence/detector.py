"""Format detection and MIME resolution for documents."""

import mimetypes
import os
from typing import Optional, Tuple

# Initialize mimetypes
mimetypes.init()

EXTENSION_MIME_MAP = {
    # Documents & Office
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".rtf": "application/rtf",
    # Text & Tabular
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    # Code & Config
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
    ".hpp": "text/x-c-header",
    ".java": "text/x-java",
    ".css": "text/css",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "text/plain",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".sql": "text/plain",
    ".sh": "text/plain",
    ".bat": "text/plain",
    ".ps1": "text/plain",
    ".log": "text/plain",
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
    # Video
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".webm": "video/webm",
    ".wmv": "video/x-ms-wmv",
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
                elif header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
                    # OLE2 container (legacy doc, ppt, xls)
                    if ext in (".doc", ".ppt", ".xls"):
                        mime = EXTENSION_MIME_MAP[ext]
                elif header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WAVE":
                    mime = "audio/wav"
                elif header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
                    mime = "audio/mpeg"
                elif header.startswith(b"fLaC"):
                    mime = "audio/flac"
                elif header.startswith(b"OggS"):
                    if ext in (".ogg", ".oga"):
                        mime = "audio/ogg"
                    elif ext == ".ogv":
                        mime = "video/ogg"
                elif len(header) >= 8 and header[4:8] == b"ftyp":
                    # MP4/M4A container
                    if ext in (".m4a", ".aac"):
                        mime = "audio/mp4"
                    else:
                        mime = "video/mp4"
                elif header.startswith(b"\x1a\x45\xdf\xa3"):
                    # Matroska / WebM
                    if ext == ".webm":
                        mime = "video/webm"
                    else:
                        mime = "video/x-matroska"
                elif header.startswith(b"\x89PNG\r\n\x1a\n"):
                    mime = "image/png"
                elif header.startswith(b"\xff\xd8\xff"):
                    mime = "image/jpeg"
                elif header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
                    mime = "image/webp"
                elif header.startswith(b"BM"):
                    mime = "image/bmp"
                elif header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
                    mime = "image/tiff"
                elif header.startswith(b"{\\rtf"):
                    mime = "application/rtf"
        except Exception:
            pass

    # Normalize format label
    if mime == "application/pdf":
        fmt = "PDF"
    elif "wordprocessingml" in mime or ext == ".docx":
        fmt = "DOCX"
    elif ext == ".doc" or mime == "application/msword":
        fmt = "DOC"
    elif "presentationml" in mime or ext == ".pptx":
        fmt = "PPTX"
    elif ext == ".ppt" or mime == "application/vnd.ms-powerpoint":
        fmt = "PPT"
    elif "spreadsheetml" in mime or ext == ".xlsx":
        fmt = "XLSX"
    elif ext == ".xls" or mime == "application/vnd.ms-excel":
        fmt = "XLS"
    elif ext == ".rtf" or mime == "application/rtf":
        fmt = "RTF"
    elif ext in (".html", ".htm") or mime == "text/html":
        fmt = "HTML"
    elif ext in (".md", ".markdown") or mime == "text/markdown":
        fmt = "MARKDOWN"
    elif ext in (".csv", ".tsv") or mime in ("text/csv", "text/tab-separated-values"):
        fmt = "CSV" if ext == ".csv" else "TSV"
    elif ext == ".json" or mime == "application/json":
        fmt = "JSON"
    elif ext == ".xml" or mime == "application/xml":
        fmt = "XML"
    elif ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".c", ".cpp", ".h", ".hpp", ".java", ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sql", ".sh", ".bat", ".ps1"):
        fmt = "CODE"
    elif mime.startswith("image/") or ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".ico", ".svg"):
        fmt = "IMAGE"
    elif mime.startswith("audio/") or ext in (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"):
        fmt = "AUDIO"
    elif mime.startswith("video/") or ext in (".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"):
        fmt = "VIDEO"
    elif mime.startswith("text/") or ext in (".txt", ".log"):
        fmt = "TEXT"
    else:
        fmt = "UNKNOWN"

    return mime, fmt


def is_supported_document(file_path: str) -> bool:
    """Checks whether the file has a supported document parser."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_DOCUMENT_EXTENSIONS
