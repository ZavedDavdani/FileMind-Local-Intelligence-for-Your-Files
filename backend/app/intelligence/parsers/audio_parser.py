"""Audio parser for FileMind Multiformat & Multimodal Intelligence.

Extracts container metadata (duration, sample rate, channels, bit rate) and
timestamped transcript segments via pluggable local transcription.
"""

import io
import logging
import os
import struct
import wave
from typing import Any, Dict, List, Optional, Tuple

from app.intelligence.models import (
    Document,
    DocumentElement,
    ElementType,
)
from app.intelligence.parsers.base import BaseParser, CorruptedDocumentError

logger = logging.getLogger("FileMind.Intelligence.Parsers.Audio")

AUDIO_PARSER_VERSION = "1.0.0"


class BaseTranscriptionEngine:
    """Pluggable audio transcription interface."""

    def transcribe(self, audio_path: str) -> Optional[List[Dict[str, Any]]]:
        """Returns list of segments: [{'start': 0.0, 'end': 15.2, 'text': '...'}]"""
        raise NotImplementedError


class LocalTranscriptionEngine(BaseTranscriptionEngine):
    """Local Whisper / Faster-Whisper audio transcription engine with graceful fallback."""

    def __init__(self, model_size: str = "base"):
        self.model_size = model_size

    def transcribe(self, audio_path: str) -> Optional[List[Dict[str, Any]]]:
        # Try faster_whisper if installed
        try:
            from faster_whisper import WhisperModel  # type: ignore
            model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path, beam_size=1)
            results = []
            for seg in segments:
                results.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()})
            return results if results else None
        except Exception:
            pass

        # Try openai-whisper if installed
        try:
            import whisper  # type: ignore
            model = whisper.load_model(self.model_size)
            res = model.transcribe(audio_path)
            results = []
            for seg in res.get("segments", []):
                results.append({"start": float(seg["start"]), "end": float(seg["end"]), "text": seg["text"].strip()})
            return results if results else None
        except Exception:
            pass

        return None


def _format_timestamp(seconds: float) -> str:
    """Formats seconds into MM:SS or HH:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def read_audio_metadata(file_path: str, ext: str) -> Dict[str, Any]:
    """Extracts duration, channels, sample rate, and format from audio file headers."""
    file_path = str(file_path)
    meta: Dict[str, Any] = {
        "duration_seconds": None,
        "sample_rate": None,
        "channels": None,
        "format": ext.lstrip(".").upper(),
    }

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return meta

    size_bytes = os.path.getsize(file_path)

    # 1. WAV extraction
    if ext == ".wav":
        try:
            with wave.open(file_path, "rb") as w:
                nchannels = w.getnchannels()
                framerate = w.getframerate()
                nframes = w.getnframes()
                meta["channels"] = nchannels
                meta["sample_rate"] = framerate
                meta["duration_seconds"] = round(nframes / float(framerate), 2) if framerate else 0.0
                return meta
        except Exception as e:
            logger.debug("WAV header parse error for %s: %s", file_path, e)

    # 2. MP3 extraction (ID3 & MPEG Frame Header sniffer)
    if ext == ".mp3":
        try:
            with open(file_path, "rb") as f:
                head = f.read(4096)
                offset = 0
                if head.startswith(b"ID3"):
                    # ID3v2 header length
                    tag_size = ((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) | ((head[8] & 0x7F) << 7) | (head[9] & 0x7F)
                    offset = 10 + tag_size
                    f.seek(offset)
                    head = f.read(4096)

                # Find MPEG sync word 0xFFE0
                for i in range(len(head) - 4):
                    if head[i] == 0xFF and (head[i + 1] & 0xE0) == 0xE0:
                        layer = (head[i + 1] >> 1) & 0x03
                        bitrate_idx = (head[i + 2] >> 4) & 0x0F
                        sample_idx = (head[i + 2] >> 2) & 0x03
                        bitrate_table = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
                        sample_table = [44100, 48000, 32000, 44100]
                        bitrate = bitrate_table[bitrate_idx] * 1000 if bitrate_idx < len(bitrate_table) else 0
                        samplerate = sample_table[sample_idx] if sample_idx < len(sample_table) else 44100
                        meta["sample_rate"] = samplerate
                        meta["channels"] = 2
                        if bitrate > 0:
                            meta["duration_seconds"] = round((size_bytes * 8) / float(bitrate), 2)
                        break
        except Exception:
            pass

    return meta


class AudioParser(BaseParser):
    """Parser for audio files (.mp3, .wav, .m4a, .flac, .ogg, .aac, .wma)."""

    def __init__(self, transcription_engine: Optional[BaseTranscriptionEngine] = None):
        self.transcription_engine = transcription_engine or LocalTranscriptionEngine()

    @property
    def parser_name(self) -> str:
        return "audio-parser"

    @property
    def parser_version(self) -> str:
        return AUDIO_PARSER_VERSION

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "audio/mpeg",
            "audio/wav",
            "audio/mp4",
            "audio/flac",
            "audio/ogg",
            "audio/aac",
            "audio/x-ms-wma",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"]

    def parse(self, file_path: str, file_id: str, mime_type: str = "audio/mpeg") -> Document:
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
            meta = read_audio_metadata(file_path, ext)
            duration = meta.get("duration_seconds")
            if duration is not None and duration > 0:
                dur_formatted = _format_timestamp(duration)
                dur_str = f"{dur_formatted} ({duration:.1f} seconds)"
            else:
                dur_str = "Unknown"

            meta_lines = [
                f"Audio Track: {filename}",
                f"Format: {meta['format']}",
                f"Duration: {dur_str}",
            ]
            if meta.get("sample_rate"):
                meta_lines.append(f"Sample Rate: {meta['sample_rate']} Hz")
            if meta.get("channels"):
                meta_lines.append(f"Channels: {meta['channels']}")

            meta_text = "\n".join(meta_lines)
            doc_obj.elements.append(
                DocumentElement(
                    element_id=f"{file_id}_elem_1",
                    element_type=ElementType.VISUAL_METADATA,
                    text=meta_text,
                    time_start=0.0,
                    time_end=duration,
                    media_type="audio",
                    extraction_method="metadata",
                    metadata=meta,
                )
            )

            elem_idx = 1

            # 2. Transcription segments
            segments = self.transcription_engine.transcribe(file_path) if self.transcription_engine else None
            if segments:
                for seg in segments:
                    elem_idx += 1
                    t_start = seg.get("start", 0.0)
                    t_end = seg.get("end", t_start + 10.0)
                    stamp_str = f"[{_format_timestamp(t_start)} - {_format_timestamp(t_end)}]"
                    seg_text = f"{stamp_str} {seg.get('text', '')}"

                    doc_obj.elements.append(
                        DocumentElement(
                            element_id=f"{file_id}_elem_{elem_idx}",
                            element_type=ElementType.TRANSCRIPT_SEGMENT,
                            text=seg_text,
                            time_start=t_start,
                            time_end=t_end,
                            media_type="audio",
                            extraction_method="transcription",
                            metadata={"start_sec": t_start, "end_sec": t_end},
                        )
                    )
            else:
                # Add summary noting audio track indexed with metadata
                elem_idx += 1
                doc_obj.elements.append(
                    DocumentElement(
                        element_id=f"{file_id}_elem_{elem_idx}",
                        element_type=ElementType.PARAGRAPH,
                        text=f"Audio recording: {filename} (Duration: {dur_str}).",
                        time_start=0.0,
                        time_end=duration,
                        media_type="audio",
                        extraction_method="metadata",
                    )
                )

        except Exception as exc:
            raise CorruptedDocumentError(f"Failed to process audio file {filename}: {str(exc)}") from exc

        return doc_obj
