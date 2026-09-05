"""Local Ollama LLM provider for FileMind ."""

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


import threading

class OllamaProvider:
    """Thin local-only HTTP client for the Ollama generation API with connection reuse."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:4b",
        connect_timeout: float = 2.0,
        read_timeout: float = 120.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._custom_client = client
        self._client: Optional[httpx.Client] = client
        self._lock = threading.Lock()

        if not self.base_url.startswith("http://127.0.0.1:"):
            raise ValueError(
                "OllamaProvider only permits the local Ollama endpoint "
                "http://127.0.0.1:<port>."
            )

    def _get_client(self) -> httpx.Client:
        if self._client is not None and not self._client.is_closed:
            return self._client
        with self._lock:
            if self._client is not None and not self._client.is_closed:
                return self._client
            timeout = httpx.Timeout(
                self.read_timeout,
                connect=self.connect_timeout,
            )
            limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
            self._client = httpx.Client(timeout=timeout, limits=limits)
            return self._client

    def close(self):
        """Closes the underlying HTTP client session."""
        with self._lock:
            if self._client is not None and not self._client.is_closed:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> OllamaResponse:
        """Generate a non-streaming response from the configured local model."""

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt must be a non-empty string.")

        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }

        opts: Dict[str, Any] = dict(options or {})
        if temperature is not None:
            opts["temperature"] = float(temperature)

        if opts:
            payload["options"] = opts

        try:
            if self._custom_client is not None:
                response = self._custom_client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
            else:
                timeout = httpx.Timeout(
                    self.read_timeout,
                    connect=self.connect_timeout,
                )
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

        if "error" in data and data["error"]:
            raise OllamaGenerationError(f"Ollama reported error: {data['error']}")

        generated_text = data.get("response")
        if not isinstance(generated_text, str):
            raise OllamaGenerationError(
                "Ollama response did not contain a valid 'response' string."
            )

        done = data.get("done")
        if done is not True:
            raise OllamaGenerationError(
                "Ollama generation did not complete successfully (done != True)."
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


def check_ollama_readiness(
    base_url: Optional[str] = None,
    target_model: Optional[str] = None,
    timeout_sec: float = 1.0,
) -> Dict[str, Any]:
    """
    Probes local Ollama daemon reachability and determines whether target_model is installed.
    Local-only, non-generating, non-blocking failure semantics.
    """
    from app.core.config import OLLAMA_BASE_URL, OLLAMA_MODEL

    url = (base_url or OLLAMA_BASE_URL).rstrip("/")
    model = target_model or OLLAMA_MODEL

    if not url.startswith("http://127.0.0.1:"):
        return {
            "is_ollama_online": False,
            "has_default_model": False,
            "model_name": model,
            "endpoint": url,
            "error": "Non-local Ollama endpoint rejected.",
        }

    try:
        resp = httpx.get(
            f"{url}/api/tags",
            timeout=httpx.Timeout(timeout_sec, connect=timeout_sec),
        )
        if resp.status_code != 200:
            return {
                "is_ollama_online": False,
                "has_default_model": False,
                "model_name": model,
                "endpoint": url,
                "error": f"Ollama HTTP {resp.status_code}",
            }

        data = resp.json()
        models = data.get("models", []) if isinstance(data, dict) else []
        installed_names = []
        for m in models:
            if isinstance(m, dict):
                n = m.get("name") or m.get("model")
                if n:
                    installed_names.append(str(n).lower().strip())

        target_lower = model.lower().strip()
        target_variants = {
            target_lower,
            target_lower if ":" in target_lower else f"{target_lower}:latest",
            f"{target_lower}:latest",
        }
        has_model = False
        for inst in installed_names:
            inst_variants = {
                inst,
                inst if ":" in inst else f"{inst}:latest",
                f"{inst}:latest",
            }
            if target_variants.intersection(inst_variants):
                has_model = True
                break

        return {
            "is_ollama_online": True,
            "has_default_model": has_model,
            "model_name": model,
            "endpoint": url,
            "error": None if has_model else f"Model '{model}' not found in installed Ollama models.",
        }
    except httpx.ConnectError:
        return {
            "is_ollama_online": False,
            "has_default_model": False,
            "model_name": model,
            "endpoint": url,
            "error": f"Unable to connect to Ollama daemon at {url}.",
        }
    except Exception as exc:
        return {
            "is_ollama_online": False,
            "has_default_model": False,
            "model_name": model,
            "endpoint": url,
            "error": str(exc),
        }


default_ollama_provider = OllamaProvider()
