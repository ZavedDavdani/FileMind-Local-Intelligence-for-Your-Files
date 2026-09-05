"""
Regression test suite for Remediation Chunk 2 (Findings 7-12).
- Finding 7: Audio/Video honest duration (no fake bitrates).
- Finding 8: Video honest keyframe representation (no fake placeholders).
- Finding 9: ImageParser vision policy default & provenance labeling.
- Finding 10: WatcherService dynamic status property.
- Finding 11: DiagnosticsResponse schema consistency & alignment.
- Finding 12: ModelSelectionRequest validation & bad request handling.
"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

from app.intelligence.parsers.audio_parser import AudioParser
from app.intelligence.parsers.video_parser import VideoParser
from app.intelligence.parsers.image_parser import ImageParser, BaseVisionEngine
from app.engine.watcher import WatcherService
from app.schemas import DiagnosticsResponse, ModelSelectionRequest, ModelStatusResponse
from app.routers.models import select_model
from fastapi import HTTPException


def test_finding7_audio_duration_honesty(tmp_path):
    """Audio parser should not invent durations from file size when mutagen cannot parse."""
    dummy_audio = tmp_path / "corrupt.mp3"
    dummy_audio.write_bytes(b"NOT_A_REAL_MP3_DATA" * 500)

    parser = AudioParser()
    result = parser.parse(str(dummy_audio), file_id="test_audio_1")

    assert result.metadata.get("duration") is None
    assert "Duration: Unknown" in result.full_text
    # Ensure no fake 128 kbps estimate was computed
    assert "estimated" not in result.full_text.lower()


def test_finding7_video_duration_honesty(tmp_path):
    """Video parser should not invent durations from file size when cv2 is absent/fails."""
    dummy_video = tmp_path / "corrupt.mp4"
    dummy_video.write_bytes(b"NOT_A_REAL_MP4_DATA" * 500)

    parser = VideoParser()
    result = parser.parse(str(dummy_video), file_id="test_video_1")

    assert result.metadata.get("duration") is None
    assert "Duration: Unknown" in result.full_text
    assert "estimated" not in result.full_text.lower()


def test_finding8_video_keyframe_honesty(tmp_path):
    """Video parser should not emit fictional image captions."""
    dummy_video = tmp_path / "sample.mkv"
    dummy_video.write_bytes(b"DUMMY_MKV_BYTES")

    parser = VideoParser()
    result = parser.parse(str(dummy_video), file_id="test_video_2")

    assert "IMAGE_CAPTION" not in result.full_text
    assert "Visual scenes" not in result.full_text


def test_finding9_image_vision_policy_and_provenance(tmp_path):
    """ImageParser should default enable_vision_model to False, and label AI captions when run."""
    parser = ImageParser()
    assert parser.enable_vision_model is False

    dummy_img = tmp_path / "test.png"
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(str(dummy_img), format="PNG")

    result = parser.parse(str(dummy_img), file_id="test_img_1")
    assert result.metadata.get("vision_model_enabled") is False
    assert "[Visual Description (AI-Generated)]" not in result.full_text

    # If enabled with mock vision engine response
    mock_engine = MagicMock(spec=BaseVisionEngine)
    mock_engine.describe_image.return_value = "A photo of a sunset over mountains."
    parser_with_vision = ImageParser(vision_engine=mock_engine, enable_vision_model=True)
    result_vision = parser_with_vision.parse(str(dummy_img), file_id="test_img_2")
    assert "[Visual Description (AI-Generated)]" in result_vision.full_text
    assert "A photo of a sunset over mountains." in result_vision.full_text


def test_finding10_watcher_status_property():
    """WatcherService should provide a dynamic status property ('active', 'stopped', 'error')."""
    watcher = WatcherService(MagicMock())
    assert watcher.status == "stopped"

    watcher.observer = MagicMock(is_alive=lambda: True)
    assert watcher.status == "active"

    watcher._has_error = True
    assert watcher.status == "error"


def test_finding11_diagnostics_response_schema():
    """DiagnosticsResponse schema must contain all expected operational & system fields."""
    diag = DiagnosticsResponse(
        platform="Windows-10",
        system_os="Windows 10",
        version="0.1.0",
        app_version="0.1.0",
        schema_version=1,
        sqlite_version="3.45.0",
        vec_version="0.1.6",
        total_folders_watched=2,
        indexed_file_count=150,
        error_count=0,
        recent_errors=[],
        watcher_status="active",
        worker_pool_status="healthy",
        database_status="healthy",
        ollama_status="healthy",
        uptime_seconds=3600.0,
    )
    dumped = diag.model_dump()
    assert dumped["system_os"] == "Windows 10"
    assert dumped["sqlite_version"] == "3.45.0"
    assert dumped["watcher_status"] == "active"
    assert dumped["database_status"] == "healthy"
    assert dumped["ollama_status"] == "healthy"
    assert dumped["uptime_seconds"] == 3600.0


def test_finding12_select_model_validation():
    """select_model must validate model names and reject invalid or malformed strings."""
    ctx = MagicMock()

    # Valid model names
    req_valid = ModelSelectionRequest(generation_model="qwen2.5:7b-instruct-q4_K_M")
    with patch("app.routers.models.check_ollama_readiness") as mock_ready:
        mock_ready.return_value = MagicMock(is_ollama_online=False, has_default_model=False)
        resp = select_model(req_valid, ctx=ctx)
        assert resp.active_generation_model == "qwen2.5:7b-instruct-q4_K_M"

    # Invalid characters
    with pytest.raises(HTTPException) as exc_info:
        select_model(ModelSelectionRequest(generation_model="llama3; rm -rf /"), ctx=ctx)
    assert exc_info.value.status_code == 400

    # Invalid empty string
    with pytest.raises(HTTPException) as exc_info2:
        select_model(ModelSelectionRequest(generation_model="   "), ctx=ctx)
    assert exc_info2.value.status_code == 400

    # Excessively long name
    with pytest.raises(HTTPException) as exc_info3:
        select_model(ModelSelectionRequest(generation_model="a" * 150), ctx=ctx)
    assert exc_info3.value.status_code == 400
