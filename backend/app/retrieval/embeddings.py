"""Local dense embedding engine for retrieval.

Uses FastEmbed (ONNX Runtime) for lightweight local inference without heavy PyTorch payload.
Supports:
- BAAI/bge-small-en-v1.5 (dim=384, default recommended candidate)
- sentence-transformers/all-MiniLM-L6-v2 (dim=384)
- nomic-ai/nomic-embed-text-v1.5 (dim=768)

Thread-lifetime contract (Batch 1 hardening):
- Model initialization runs in exactly ONE daemon thread at a time.
- Callers block for up to `load_timeout` seconds, then receive
  EmbeddingLoadTimeoutError and the BM25 fallback path activates.
- The daemon thread is NOT killable from Python (language constraint), but:
    * There is at most 1 such thread alive at any moment.
    * It terminates when FastEmbed's internal retry schedule expires (~40 s max).
    * It is a daemon thread and therefore dies with the process.
    * No task queue accumulates — subsequent callers share the same daemon thread
      and the same threading.Event rather than queuing additional work items.
- This replaces the previous ThreadPoolExecutor design, which (a) could not
  cancel a running thread via future.cancel() and (b) accumulated queued tasks
  while the single worker was blocked.
"""

import logging
import threading
import time
from typing import Any, List, Optional
import numpy as np

from app.core.config import EMBEDDING_RETRY_COOLDOWN_SECONDS

logger = logging.getLogger("FileMind.Retrieval.Embeddings")

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Maximum seconds to wait for model initialization before raising.
# FastEmbed's internal HTTP-retry schedule: 3 s -> 9 s -> 27 s ≈ 39 s total.
# During normal operation the model is already cached locally and loads in < 2 s.
EMBEDDING_LOAD_TIMEOUT_SECONDS = 15.0
RETRY_COOLDOWN_SECONDS = EMBEDDING_RETRY_COOLDOWN_SECONDS

MODEL_DIMENSIONS = {
    "BAAI/bge-small-en-v1.5": 384,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "nomic-ai/nomic-embed-text-v1.5": 768,
}


class EmbeddingLoadTimeoutError(RuntimeError):
    """Raised when the embedding model cannot be loaded within the configured timeout."""
    pass


class EmbeddingEngine:
    """Manages local embedding model inference with deferred lazy loading.

    Initialization is guarded by a single bounded daemon thread and a
    threading.Event so that:
    - Thread count never exceeds 1 (no accumulation).
    - No task queue accumulates (all callers share one Event).
    - Callers that exceed load_timeout receive EmbeddingLoadTimeoutError
      immediately; the background thread continues to its natural end (~40 s)
      but is the ONLY such thread and dies at process exit.
    - If the background thread eventually succeeds (network recovered before
      40 s), _model is set and all subsequent callers use the O(1) fast-path.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        load_timeout: float = EMBEDDING_LOAD_TIMEOUT_SECONDS,
        retry_cooldown: float = RETRY_COOLDOWN_SECONDS,
        model_registry: Optional[Any] = None,
    ):
        self.model_name = model_name
        self._model_registry = model_registry
        if model_name in MODEL_DIMENSIONS:
            self.dimension = MODEL_DIMENSIONS[model_name]
        elif self.model_registry.get_model(f"fastembed:{model_name}") is not None:
            mod_info = self.model_registry.get_model(f"fastembed:{model_name}")
            self.dimension = mod_info.dimension if mod_info and mod_info.dimension else 384
        else:
            raise ValueError(
                f"Unknown or unconfigured embedding model '{model_name}'. "
                f"Model must be registered in MODEL_DIMENSIONS or ModelRegistry."
            )
        self.load_timeout = load_timeout
        self.retry_cooldown = retry_cooldown
        self._model = None
        self._lock = threading.Lock()
        # Single init-thread state — no executor, no task queue.
        self._init_thread: Optional[threading.Thread] = None
        self._init_done = threading.Event()   # set when _run_init finishes (success or fail)
        self._init_error: Optional[Exception] = None
        self._last_failure_time: float = 0.0

    @property
    def model_registry(self):
        if self._model_registry is not None:
            return self._model_registry
        from app.retrieval.model_registry import default_model_registry
        return default_model_registry

    @property
    def model_version(self) -> str:
        return "1.0.0"

    def get_identity(self) -> dict:
        return {
            "provider": "fastembed",
            "model_name": self.model_name,
            "model_version": self.model_version,
            "dimension": self.dimension,
        }

    @property
    def is_in_cooldown(self) -> bool:
        """Returns True if the engine is currently in failure cooldown period."""
        if self._init_error is None or self._last_failure_time <= 0.0:
            return False
        return (time.time() - self._last_failure_time) < self.retry_cooldown

    def reset_init_state(self) -> None:
        """Resets failure state to force a clean re-initialization on next call."""
        with self._lock:
            self._init_error = None
            self._last_failure_time = 0.0
            if self._init_thread is None or not self._init_thread.is_alive():
                self._init_done.clear()
                self._init_thread = None

    def _run_init(self) -> None:
        """Daemon thread: loads the FastEmbed TextEmbedding model and signals _init_done.

        Runs at most ONCE per load attempt. Any subsequent reader returning
        from _init_done.wait() observes a fully-initialised model (GIL + Event
        provide the required happens-before).
        """
        try:
            from app.retrieval.model_registry import ModelReadiness
            self.model_registry.update_readiness(
                f"fastembed:{self.model_name}",
                ModelReadiness.LOADING,
            )
            from fastembed import TextEmbedding
            logger.info(
                "Embedding init thread starting: %s (daemon=True, bounded to ~40 s max)",
                self.model_name,
            )
            model = TextEmbedding(model_name=self.model_name)
            self._model = model          # visible to all waiters after _init_done.set()
            self._init_error = None
            self._last_failure_time = 0.0
            self.model_registry.update_readiness(
                f"fastembed:{self.model_name}",
                ModelReadiness.READY,
            )
            logger.info("Embedding init thread succeeded: %s", self.model_name)
        except Exception as exc:
            self._init_error = exc
            self._last_failure_time = time.time()
            from app.retrieval.model_registry import ModelReadiness
            self.model_registry.update_readiness(
                f"fastembed:{self.model_name}",
                ModelReadiness.FAILED,
                error=str(exc),
            )
            logger.error("Embedding init thread failed: %s: %s", self.model_name, exc)
        finally:
            self._init_done.set()        # always release all waiters


    def _ensure_loaded(self) -> None:
        """Deferred lazy loading with a single bounded daemon thread.

        Algorithm:
        1. Fast-path: if _model is already set, return immediately (no lock).
        2. Acquire lock:
           a. Re-check _model (double-checked locking).
           b. If failed recently within retry_cooldown, fail fast without spawning new thread.
           c. If no alive init thread: clear event, start a new daemon thread.
           d. (If a thread is already running: all callers share the same thread.)
        3. Release lock; wait on _init_done up to load_timeout.
        4. On timeout: raise EmbeddingLoadTimeoutError without blocking further.
        5. On init failure: propagate the exception and record failure timestamp.
        """
        # --- Fast-path (no lock required) ---
        if self._model is not None:
            return

        now = time.time()
        with self._lock:
            if self._model is not None:
                return

            # Fail fast if recent initialization failed within retry cooldown
            if self._init_error is not None and (now - self._last_failure_time) < self.retry_cooldown:
                err = self._init_error
                raise RuntimeError(
                    f"Embedding model initialization failed: {err}"
                ) from err

            # Start a new init thread only if none is already running.
            if self._init_thread is None or not self._init_thread.is_alive():
                self._init_done.clear()
                self._init_error = None
                self._init_thread = threading.Thread(
                    target=self._run_init,
                    name="FileMind-EmbeddingInit",
                    daemon=True,          # dies with the process
                )
                self._init_thread.start()
                logger.info(
                    "Embedding init thread launched (timeout: %.1f s)", self.load_timeout
                )
            # else: thread is alive, all callers share the same _init_done Event.

        # --- Wait outside the lock so other threads are not serialised here ---
        completed = self._init_done.wait(timeout=self.load_timeout)

        if not completed:
            msg = (
                f"Embedding model initialization timed out after {self.load_timeout:.0f} s "
                f"({self.model_name}). Dense retrieval unavailable; BM25 fallback active. "
                f"Background init thread is still running (daemon=True, self-bounded to ~40 s)."
            )
            logger.error(msg)
            raise EmbeddingLoadTimeoutError(msg)

        # Init thread signalled completion — check for error.
        if self._init_error is not None:
            self._last_failure_time = time.time()
            err = self._init_error
            raise RuntimeError(
                f"Embedding model initialization failed: {err}"
            ) from err
        # _model is now set (written by _run_init before _init_done.set()).


    def embed_texts(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Generates normalized dense embedding vectors for a list of texts."""
        if not texts:
            return []
        self._ensure_loaded()
        if "nomic" in self.model_name.lower():
            prefixed_texts = [
                t if t.startswith("search_document: ") else f"search_document: {t}"
                for t in texts
            ]
        else:
            prefixed_texts = texts
        embeddings_iter = self._model.embed(prefixed_texts, batch_size=batch_size)
        vectors = []
        for emb in embeddings_iter:
            vec = np.array(emb, dtype=np.float32)
            # L2 normalize vector for cosine similarity
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec.tolist())
        return vectors

    def embed_query(self, query_text: str) -> List[float]:
        """Generates normalized dense embedding vector for a single query."""
        self._ensure_loaded()
        # Nomic uses specific prefix for search queries
        if "nomic" in self.model_name.lower():
            text = query_text if query_text.startswith("search_query: ") else f"search_query: {query_text}"
        else:
            text = query_text
        embeddings = list(self._model.embed([text]))
        if not embeddings:
            return [0.0] * self.dimension
        vec = np.array(embeddings[0], dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()


# Global default instance (lazy)
default_embedding_engine = EmbeddingEngine(DEFAULT_MODEL_NAME)
