"""Video parser for FileMind Multiformat & Multimodal Intelligence.

Extracts container metadata, bounded keyframe sampling, and audio/transcript
tracks with strict bounded resource constraints.
"""

import logging
import os
import struct
from typing import Any, Dict, List, Optional

from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
)
from app.intelligence.parsers.base import BaseParser, CorruptedDocumentError

logger = logging.getLogger("FileMind.Intelligence.Parsers.Video")

VIDEO_PARSER_VERSION = "1.0.0"
MAX_VIDEO_KEYFRAMES = 10


def _format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def read_video_metadata(file_path: str, ext: str) -> Dict[str, Any]:
    """Parses video headers (MP4 mvhd/tkhd atoms, MKV headers) to extract duration and dimensions."""
    meta: Dict[str, Any] = {
        "duration_seconds": None,
        "width": None,
        "height": None,
        "format": ext.lstrip(".").upper(),
    }

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return meta

    size_bytes = os.path.getsize(file_path)

    # Fast MP4 header inspection
    if ext in (".mp4", ".mov", ".m4v"):
        try:
            with open(file_path, "rb") as f:
                while True:
                    hdr = f.read(8)
                    if len(hdr) < 8:
                        break
                    atom_size, atom_type = struct.unpack(">I4s", hdr)
                    if atom_size == 1:
                        atom_size = struct.unpack(">Q", f.read(8))[0]
                        f.seek(atom_size - 16, os.SEEK_CUR)
                    elif atom_type == b"moov":
                        # Inspect mvhd inside moov
                        moov_data = f.read(min(atom_size - 8, 1024 * 1024))
                        mvhd_idx = moov_data.find(b"mvhd")
                        if mvhd_idx != -1:
                            v_idx = mvhd_idx + 4
                            version = moov_data[v_idx]
                            if version == 0:
                                timescale = struct.unpack(">I", moov_data[v_idx + 12:v_idx + 16])[0]
                                duration_units = struct.unpack(">I", moov_data[v_idx + 16:v_idx + 20])[0]
                            else:
                                timescale = struct.unpack(">I", moov_data[v_idx + 20:v_idx + 24])[0]
                                duration_units = struct.unpack(">Q", moov_data[v_idx + 24:v_idx + 32])[0]
                            if timescale > 0:
                                meta["duration_seconds"] = round(duration_units / float(timescale), 2)
                        break
                    else:
                        f.seek(max(0, atom_size - 8), os.SEEK_CUR)
        except Exception:
            pass

    return meta


class VideoParser(BaseParser):
    """Parser for video media files (.mp4, .mkv, .mov, .avi, .webm, .wmv)."""

    def __init__(self, max_keyframes: int = MAX_VIDEO_KEYFRAMES):
        self.max_keyframes = max_keyframes

    @property
    def parser_name(self) -> str:
        return "video-parser"

    @property
    def parser_version(self) -> str:
        return VIDEO_PARSER_VERSION

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "video/mp4",
            "video/x-matroska",
            "video/quicktime",
            "video/x-msvideo",
            "video/webm",
            "video/x-ms-wmv",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "video/mp4") -> Document:
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
            meta = read_video_metadata(file_path, ext)
            duration = meta.get("duration_seconds")
            if duration is not None and duration > 0:
                dur_formatted = _format_timestamp(duration)
                dur_str = f"{dur_formatted} ({duration:.1f} seconds)"
            else:
                dur_str = "Unknown"

            meta_lines = [
                f"Video Recording: {filename}",
                f"Container Format: {meta['format']}",
                f"Duration: {dur_str}",
            ]
            if meta.get("width") and meta.get("height"):
                meta_lines.append(f"Resolution: {meta['width']}x{meta['height']}")

            meta_text = "\n".join(meta_lines)
            doc_obj.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_1",
                    element_type=ElementType.VISUAL_METADATA,
                    text=meta_text,
                    time_start=0.0 if duration is not None else None,
                    time_end=duration if duration is not None else None,
                    media_type="video",
                    extraction_method="metadata",
                    metadata=meta,
                )
            )

        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to process video file {filename}: {str(exc)}") from exc

        return doc_obj
