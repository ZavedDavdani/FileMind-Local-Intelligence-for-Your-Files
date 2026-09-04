"""Local Cross-Encoder Reranking Engine for Phase 4 retrieval.

Uses FastEmbed (ONNX Runtime) TextCrossEncoder for lightweight local inference
without heavy PyTorch payload.
Supports:
- BAAI/bge-reranker-base (default)
- Other FastEmbed supported cross-encoders (e.g. ms-marco, jinaai)

Thread-lifetime contract (consistent with EmbeddingEngine in embeddings.py):
- Model initialization runs in exactly ONE daemon thread at a time.
- Callers block for up to `load_timeout` seconds, then receive
  RerankerLoadTimeoutError and hybrid search gracefully falls back to RRF.
- The daemon thread dies with the process.
- No task queue accumulates — subsequent callers share the same daemon thread
  and threading.Event.
"""

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

from app.core.config import (
    DEFAULT_RERANK_MODEL_NAME,
    RERANKER_LOAD_TIMEOUT_SECONDS,
    RERANKER_RETRY_COOLDOWN_SECONDS,
)

logger = logging.getLogger("FileMind.Retrieval.Reranker")


def _sigmoid(x: float) -> float:
    """Computes stable sigmoid to map unbounded cross-encoder logits to (0, 1) probabilities."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


class RerankerLoadTimeoutError(RuntimeError):
    """Raised when the reranker model cannot be loaded within the configured timeout."""
    pass


class Reranker:
    """Manages local cross-encoder reranking inference with deferred lazy loading."""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANK_MODEL_NAME,
        load_timeout: float = RERANKER_LOAD_TIMEOUT_SECONDS,
        retry_cooldown: float = RERANKER_RETRY_COOLDOWN_SECONDS,
        model_registry: Optional[Any] = None,
    ):
        self.model_name = model_name
        self.load_timeout = load_timeout
        self.retry_cooldown = retry_cooldown
        self._model_registry = model_registry
        self._model = None
        self._lock = threading.Lock()
        self._init_thread: Optional[threading.Thread] = None
        self._init_done = threading.Event()
        self._init_error: Optional[Exception] = None
        self._last_failure_time: float = 0.0

    @property
    def model_registry(self):
        if self._model_registry is not None:
            return self._model_registry
        from app.retrieval.model_registry import default_model_registry
        return default_model_registry

    def reset_init_state(self) -> None:
        """Resets failure state to force a clean re-initialization on next call."""
        with self._lock:
            self._init_error = None
            self._last_failure_time = 0.0
            if self._init_thread is None or not self._init_thread.is_alive():
                self._init_done.clear()

    def _run_init(self) -> None:
        """Daemon thread: loads the FastEmbed TextCrossEncoder model and signals _init_done."""
        try:
            from app.retrieval.model_registry import ModelReadiness
            self.model_registry.update_readiness(
                f"fastembed:{self.model_name}",
                ModelReadiness.LOADING,
            )
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            logger.info(
                "Reranker init thread starting: %s (daemon=True, bounded to ~40 s max)",
                self.model_name,
            )
            model = TextCrossEncoder(model_name=self.model_name)
            self._model = model
            self._init_error = None
            self._last_failure_time = 0.0
            self.model_registry.update_readiness(
                f"fastembed:{self.model_name}",
                ModelReadiness.READY,
            )
            logger.info("Reranker init thread succeeded: %s", self.model_name)
        except Exception as exc:
            self._init_error = exc
            self._last_failure_time = time.time()
            from app.retrieval.model_registry import ModelReadiness
            self.model_registry.update_readiness(
                f"fastembed:{self.model_name}",
                ModelReadiness.FAILED,
                error=str(exc),
            )
            logger.error("Reranker init thread failed: %s: %s", self.model_name, exc)
        finally:
            self._init_done.set()


    def _ensure_loaded(self) -> None:
        """Deferred lazy loading with single bounded daemon thread."""
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
                    f"Reranker model initialization failed: {err}"
                ) from err

            if self._init_thread is None or not self._init_thread.is_alive():
                self._init_done.clear()
                self._init_error = None
                self._init_thread = threading.Thread(
                    target=self._run_init,
                    name="FileMind-RerankerInit",
                    daemon=True,
                )
                self._init_thread.start()
                logger.info(
                    "Reranker init thread launched (timeout: %.1f s)", self.load_timeout
                )

        completed = self._init_done.wait(timeout=self.load_timeout)

        if not completed:
            msg = (
                f"Reranker model initialization timed out after {self.load_timeout:.0f} s "
                f"({self.model_name}). Hybrid search falling back to RRF ranking. "
                f"Background init thread is still running (daemon=True)."
            )
            logger.error(msg)
            raise RerankerLoadTimeoutError(msg)

        if self._init_error is not None:
            self._last_failure_time = time.time()
            err = self._init_error
            raise RuntimeError(
                f"Reranker model initialization failed: {err}"
            ) from err


    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Reranks candidate chunks using the cross-encoder model.

        Preserves:
        - All chunk provenance fields (source_file, source_path, page, section, h1/h2, lines, chars, hash, chunk_id, file_id)
        - All underlying retrieval evidence (lexical_score, dense_score, rrf_score, lexical_rank, dense_rank)
        - Authentic chunk snippets

        Adds:
        - reranker_score (float)
        - Updates score to reranker_score
        - Applies deterministic tie-breaking:
          reranker_score DESC -> rrf_score DESC -> dense_score DESC -> lexical_score DESC -> chunk_id ASC
        """
        if not candidates:
            return []

        self._ensure_loaded()

        # Extract authentic document text from candidate chunks
        documents = [c.get("content", "") for c in candidates]

        # Run cross-encoder scoring
        scores_iter = self._model.rerank(query, documents, batch_size=32)
        raw_scores = list(scores_iter)

        if len(raw_scores) != len(candidates):
            logger.warning(
                "Reranker returned %d scores for %d candidates; falling back to candidate order",
                len(raw_scores),
                len(candidates),
            )
            # If length mismatch, assign default fallback scores to avoid dropping candidates
            if len(raw_scores) < len(candidates):
                raw_scores.extend([0.0] * (len(candidates) - len(raw_scores)))
            else:
                raw_scores = raw_scores[:len(candidates)]

        scored_items: List[Dict[str, Any]] = []
        for cand, score in zip(candidates, raw_scores):
            score_float = round(_sigmoid(float(score)), 6)
            item = dict(cand)
            item["reranker_score"] = score_float
            item["score"] = score_float
            # Explicitly preserve underlying score metadata
            if "rrf_score" in cand:
                item["rrf_score"] = cand["rrf_score"]
            if "dense_score" in cand:
                item["dense_score"] = cand["dense_score"]
            if "lexical_score" in cand:
                item["lexical_score"] = cand["lexical_score"]
            # Preserve existing retrieval_method or mark hybrid
            if not item.get("retrieval_method"):
                item["retrieval_method"] = "hybrid"
            scored_items.append(item)

        # Deterministic multi-level tie-breaking:
        # 1. reranker_score DESC
        # 2. rrf_score DESC
        # 3. dense_score DESC
        # 4. lexical_score DESC
        # 5. chunk_id ASC
        scored_items.sort(
            key=lambda x: (
                -float(x.get("reranker_score", 0.0)),
                -float(x.get("rrf_score") if x.get("rrf_score") is not None else 0.0),
                -float(x.get("dense_score") if x.get("dense_score") is not None else 0.0),
                -float(x.get("lexical_score") if x.get("lexical_score") is not None else 0.0),
                str(x.get("chunk_id", "")),
            )
        )


        final_results: List[Dict[str, Any]] = []
        for rank, item in enumerate(scored_items[:top_k], start=1):
            item_copy = dict(item)
            item_copy["rank"] = rank
            final_results.append(item_copy)

        return final_results


# Global default instance (lazy)
default_reranker = Reranker(DEFAULT_RERANK_MODEL_NAME)
