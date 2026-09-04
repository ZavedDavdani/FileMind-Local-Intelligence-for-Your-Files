"""Tests for Bug 2: Embedding & Reranker Retry Cooldown.

Verifies:
1. Embedding fail-fast within cooldown without spawning new threads.
2. Embedding retry allowed after cooldown expiration.
3. Reranker fail-fast within cooldown without spawning new threads.
4. Reranker retry allowed after cooldown expiration.
5. Environment variable overrides for config cooldown constants.
"""

import os
import time
import unittest.mock as mock
import pytest

from app.core.config import (
    EMBEDDING_RETRY_COOLDOWN_SECONDS,
    RERANKER_RETRY_COOLDOWN_SECONDS,
)
from app.retrieval.embeddings import EmbeddingEngine
from app.retrieval.reranker import Reranker


def test_embedding_retry_cooldown_defaults():
    assert EMBEDDING_RETRY_COOLDOWN_SECONDS == 30.0
    assert RERANKER_RETRY_COOLDOWN_SECONDS == 30.0


def test_config_env_var_overrides(monkeypatch):
    monkeypatch.setenv("FILEMIND_EMBED_RETRY_COOLDOWN_SEC", "42.5")
    monkeypatch.setenv("FILEMIND_RERANK_RETRY_COOLDOWN_SEC", "15.0")

    import importlib
    import app.core.config as cfg
    importlib.reload(cfg)

    assert cfg.EMBEDDING_RETRY_COOLDOWN_SECONDS == 42.5
    assert cfg.RERANKER_RETRY_COOLDOWN_SECONDS == 15.0

    # Reload again to restore default
    monkeypatch.delenv("FILEMIND_EMBED_RETRY_COOLDOWN_SEC", raising=False)
    monkeypatch.delenv("FILEMIND_RERANK_RETRY_COOLDOWN_SEC", raising=False)
    importlib.reload(cfg)


def test_embedding_fail_fast_within_cooldown(monkeypatch):
    current_time = [1000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    engine = EmbeddingEngine(retry_cooldown=30.0, load_timeout=1.0)

    with mock.patch("fastembed.TextEmbedding", side_effect=RuntimeError("FastEmbed connection timeout")):
        # First call fails and records failure time
        with pytest.raises(RuntimeError, match="FastEmbed connection timeout"):
            engine.embed_texts(["test text"])

    assert engine._init_error is not None
    assert engine._last_failure_time == 1000.0
    initial_thread = engine._init_thread

    # Advance time by 10s (within 30s cooldown)
    current_time[0] = 1010.0

    # Call again: should fail-fast without launching new thread or calling fastembed
    with mock.patch("threading.Thread") as mock_thread:
        with pytest.raises(RuntimeError, match="FastEmbed connection timeout"):
            engine.embed_texts(["test text"])
        mock_thread.assert_not_called()

    # Thread reference unchanged
    assert engine._init_thread is initial_thread


def test_embedding_retry_allowed_after_cooldown(monkeypatch):
    current_time = [1000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    engine = EmbeddingEngine(retry_cooldown=30.0, load_timeout=1.0)

    # First attempt fails
    with mock.patch("fastembed.TextEmbedding", side_effect=RuntimeError("FastEmbed failure")):
        with pytest.raises(RuntimeError, match="FastEmbed failure"):
            engine.embed_texts(["test text"])

    assert engine._last_failure_time == 1000.0

    # Advance time past 30s cooldown
    current_time[0] = 1035.0

    # Mock successful FastEmbed TextEmbedding
    mock_model_instance = mock.MagicMock()
    mock_model_instance.embed.return_value = [[0.1] * 384]

    with mock.patch("fastembed.TextEmbedding", return_value=mock_model_instance):
        result = engine.embed_texts(["test text"])

    assert len(result) == 1
    assert len(result[0]) == 384
    assert engine._model is mock_model_instance
    assert engine._init_error is None


def test_reranker_fail_fast_within_cooldown(monkeypatch):
    current_time = [2000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    reranker = Reranker(retry_cooldown=30.0, load_timeout=1.0)

    with mock.patch("fastembed.rerank.cross_encoder.TextCrossEncoder", side_effect=RuntimeError("Reranker model load failed")):
        with pytest.raises(RuntimeError, match="Reranker model load failed"):
            reranker.rerank("query", [{"text": "doc1"}])

    assert reranker._init_error is not None
    assert reranker._last_failure_time == 2000.0
    initial_thread = reranker._init_thread

    # Advance time by 15s (within 30s cooldown)
    current_time[0] = 2015.0

    with mock.patch("threading.Thread") as mock_thread:
        with pytest.raises(RuntimeError, match="Reranker model load failed"):
            reranker.rerank("query", [{"text": "doc1"}])
        mock_thread.assert_not_called()

    assert reranker._init_thread is initial_thread


def test_reranker_retry_allowed_after_cooldown(monkeypatch):
    current_time = [2000.0]
    monkeypatch.setattr(time, "time", lambda: current_time[0])

    reranker = Reranker(retry_cooldown=30.0, load_timeout=1.0)

    with mock.patch("fastembed.rerank.cross_encoder.TextCrossEncoder", side_effect=RuntimeError("Initial error")):
        with pytest.raises(RuntimeError, match="Initial error"):
            reranker.rerank("query", [{"text": "doc1"}])

    # Advance time past 30s
    current_time[0] = 2031.0

    mock_cross_encoder = mock.MagicMock()
    mock_cross_encoder.rerank.return_value = [0.85]

    with mock.patch("fastembed.rerank.cross_encoder.TextCrossEncoder", return_value=mock_cross_encoder):
        results = reranker.rerank("query", [{"text": "doc1"}])

    assert len(results) == 1
    assert "reranker_score" in results[0]
    assert reranker._model is mock_cross_encoder
    assert reranker._init_error is None
