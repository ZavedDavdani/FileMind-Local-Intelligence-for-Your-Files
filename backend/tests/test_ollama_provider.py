import pytest

from app.ai.ollama_provider import (
    OllamaConnectionError,
    OllamaGenerationError,
    OllamaProvider,
    OllamaTimeoutError,
)


def test_provider_rejects_non_local_endpoint():
    with pytest.raises(ValueError):
        OllamaProvider(base_url="https://example.com:11434")


def test_provider_rejects_empty_prompt():
    provider = OllamaProvider()

    with pytest.raises(ValueError):
        provider.generate("")


def test_provider_rejects_whitespace_prompt():
    provider = OllamaProvider()

    with pytest.raises(ValueError):
        provider.generate("   ")


def test_provider_local_generation():
    provider = OllamaProvider(
        model="qwen3:4b",
        read_timeout=120.0,
    )

    result = provider.generate(
        "Reply with exactly: FILEMIND_PROVIDER_OK"
    )

    assert result.model == "qwen3:4b"
    assert result.done is True
    assert result.response.strip() == "FILEMIND_PROVIDER_OK"
    assert result.done_reason is not None


def test_provider_response_is_serializable():
    provider = OllamaProvider(
        model="qwen3:4b",
        read_timeout=120.0,
    )

    result = provider.generate(
        "Reply with exactly: FILEMIND_SERIALIZATION_OK"
    )

    payload = result.to_dict()

    assert payload["model"] == "qwen3:4b"
    assert payload["response"].strip() == "FILEMIND_SERIALIZATION_OK"
    assert payload["done"] is True