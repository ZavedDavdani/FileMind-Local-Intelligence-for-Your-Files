"""Local Ollama LLM provider for FileMind Phase 5."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


class OllamaError(RuntimeError):
    """Base exception for local Ollama failures."""


class OllamaConnectionError(OllamaError):
    """Raised when the Ollama runtime cannot be reached."""


class OllamaTimeoutError(OllamaError):
    """Raised when an Ollama request exceeds its timeout."""


class OllamaGenerationError(OllamaError):
    """Raised when Ollama returns an invalid or unsuccessful response."""


@dataclass(frozen=True)
class OllamaResponse:
    """Validated response returned by the local Ollama provider."""

    model: str
    response: str
    done: bool
    done_reason: Optional[str]
    prompt_eval_count: Optional[int]
    eval_count: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "response": self.response,
            "done": self.done,
            "done_reason": self.done_reason,
            "prompt_eval_count": self.prompt_eval_count,
            "eval_count": self.eval_count,
        }


class OllamaProvider:
    """Thin local-only HTTP client for the Ollama generation API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:4b",
        connect_timeout: float = 2.0,
        read_timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        if not self.base_url.startswith("http://127.0.0.1:"):
            raise ValueError(
                "OllamaProvider only permits the local Ollama endpoint "
                "http://127.0.0.1:<port>."
            )

    def generate(self, prompt: str) -> OllamaResponse:
        """Generate a non-streaming response from the configured local model."""

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt must be a non-empty string.")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }

        timeout = httpx.Timeout(
            self.read_timeout,
            connect=self.connect_timeout,
        )

        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=timeout,
            )
        except httpx.ConnectError as exc:
            raise OllamaConnectionError(
                f"Unable to connect to local Ollama at {self.base_url}."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama request timed out after {self.read_timeout:.1f} seconds."
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaConnectionError(
                f"Ollama HTTP request failed: {exc}"
            ) from exc

        if response.status_code != 200:
            raise OllamaGenerationError(
                f"Ollama returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaGenerationError(
                "Ollama returned a non-JSON response."
            ) from exc

        if not isinstance(data, dict):
            raise OllamaGenerationError(
                "Ollama returned an invalid response object."
            )

        generated_text = data.get("response")
        if not isinstance(generated_text, str):
            raise OllamaGenerationError(
                "Ollama response did not contain a valid 'response' string."
            )

        done = data.get("done")
        if done is not True:
            raise OllamaGenerationError(
                "Ollama generation did not complete successfully."
            )

        return OllamaResponse(
            model=str(data.get("model") or self.model),
            response=generated_text,
            done=True,
            done_reason=(
                str(data["done_reason"])
                if data.get("done_reason") is not None
                else None
            ),
            prompt_eval_count=(
                int(data["prompt_eval_count"])
                if data.get("prompt_eval_count") is not None
                else None
            ),
            eval_count=(
                int(data["eval_count"])
                if data.get("eval_count") is not None
                else None
            ),
        )
