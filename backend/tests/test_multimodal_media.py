"""Tests for multimodal image, audio, and video parsers and metadata extractors."""

import io
from pathlib import Path
import struct
import wave
import pytest

from app.intelligence.models import ElementType, Document
from app.intelligence.parsers.audio_parser import AudioParser
from app.intelligence.parsers.image_parser import ImageParser
from app.intelligence.parsers.video_parser import VideoParser


class TestImageParser:
    def test_image_metadata_and_dimensions(self, tmp_path):
        from PIL import Image

        img_file = tmp_path / "diagram.png"
        img = Image.new("RGB", (800, 600), color=(73, 109, 137))
        img.save(img_file, format="PNG")

        parser = ImageParser()
        doc = parser.parse(img_file, file_id="file-img-1", mime_type="image/png")

        assert doc.parser_name == "image-parser"
        assert len(doc.elements) >= 1
        meta_el = doc.elements[0]
        assert meta_el.element_type == ElementType.VISUAL_METADATA
        assert meta_el.media_type == "image"
        assert meta_el.extraction_method == "metadata"
        assert "800 x 600" in meta_el.text
        assert meta_el.metadata.get("width") == 800
        assert meta_el.metadata.get("height") == 600

    def test_svg_xml_extraction(self, tmp_path):
        svg_file = tmp_path / "architecture.svg"
        svg_content = (
            '<svg width="500" height="300" xmlns="http://www.w3.org/2000/svg">\n'
            '  <title>FileMind System Topology</title>\n'
            '  <desc>Shows local hybrid retrieval and vector store</desc>\n'
            '  <text x="20" y="50">FastEmbed ONNX In-Process Embedding</text>\n'
            '</svg>\n'
        )
        svg_file.write_text(svg_content, encoding="utf-8")

        parser = ImageParser()
        doc = parser.parse(svg_file, file_id="file-svg-1", mime_type="image/svg+xml")

        assert len(doc.elements) >= 1
        combined = " ".join(e.text for e in doc.elements)
        assert "FileMind System Topology" in combined
        assert "FastEmbed ONNX" in combined


class TestAudioParser:
    def test_wav_container_metadata_and_segments(self, tmp_path):
        wav_file = tmp_path / "meeting_notes.wav"
        sample_rate = 16000
        duration_seconds = 3.0
        num_frames = int(sample_rate * duration_seconds)

        # Generate a minimal valid uncompressed 16-bit mono PCM WAV file
        with wave.open(str(wav_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * num_frames)

        parser = AudioParser()
        doc = parser.parse(wav_file, file_id="file-audio-1", mime_type="audio/wav")

        assert doc.parser_name == "audio-parser"
        assert len(doc.elements) >= 1
        meta_el = doc.elements[0]
        assert meta_el.media_type == "audio"
        assert "Duration" in meta_el.text
        assert meta_el.metadata.get("sample_rate") == 16000
        assert meta_el.metadata.get("channels") == 1
        assert abs(meta_el.metadata.get("duration_seconds", 0) - 3.0) < 0.1


class TestVideoParser:
    def test_mp4_header_and_bounded_sampling(self, tmp_path):
        mp4_file = tmp_path / "product_demo.mp4"
        ftyp_atom = struct.pack(">I4s4sI", 24, b"ftyp", b"isom", 512) + b"isomiso2mp41"
        moov_atom = struct.pack(">I4s", 16, b"moov") + b"\x00" * 8
        mp4_file.write_bytes(ftyp_atom + moov_atom)

        parser = VideoParser()
        doc = parser.parse(mp4_file, file_id="file-video-1", mime_type="video/mp4")

        assert doc.parser_name == "video-parser"
        assert len(doc.elements) >= 1
        meta_el = doc.elements[0]
        assert meta_el.media_type == "video"
        assert "Video Recording" in meta_el.text or "Container Format" in meta_el.text
