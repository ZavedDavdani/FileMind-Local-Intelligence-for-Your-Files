"""Local dense embedding engine for Phase 3 retrieval.

Uses FastEmbed (ONNX Runtime) for lightweight local inference without heavy PyTorch payload.
Supports:
- BAAI/bge-small-en-v1.5 (dim=384, default recommended candidate)
- sentence-transformers/all-MiniLM-L6-v2 (dim=384)
- nomic-ai/nomic-embed-text-v1.5 (dim=768)
"""

import logging
import threading
from typing import List, Optional, Union
import numpy as np

logger = logging.getLogger("FileMind.Retrieval.Embeddings")

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"

MODEL_DIMENSIONS = {
    "BAAI/bge-small-en-v1.5": 384,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "nomic-ai/nomic-embed-text-v1.5": 768,
}


class EmbeddingEngine:
    """Manages local embedding model inference with deferred lazy loading."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self.model_name = model_name
        self.dimension = MODEL_DIMENSIONS.get(model_name, 384)
        self._model = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        """Deferred lazy loading of the underlying ONNX model."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is None:
                try:
                    from fastembed import TextEmbedding
                    logger.info("Initializing local embedding model: %s", self.model_name)
                    self._model = TextEmbedding(model_name=self.model_name)
                    logger.info("Local embedding model loaded successfully: %s", self.model_name)
                except Exception as exc:
                    logger.error("Failed to load embedding model %s: %s", self.model_name, str(exc))
                    raise RuntimeError(f"Embedding model initialization failed: {exc}") from exc

    def embed_texts(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Generates normalized dense embedding vectors for a list of texts."""
        if not texts:
            return []
        self._ensure_loaded()
        embeddings_iter = self._model.embed(texts, batch_size=batch_size)
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
            text = f"search_query: {query_text}"
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
