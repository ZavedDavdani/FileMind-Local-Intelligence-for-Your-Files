"""Model Registry foundation and readiness tracking for FileMind retrieval & AI infrastructure.

Features:
- Authoritative identity source for embedding, reranking, and future LLM models.
- Structured readiness state machine: UNAVAILABLE, PREPARING, DOWNLOADING, LOADING, READY, DEGRADED, FAILED.
- Extensible metadata tracking: provider, version/revision, dimension, hardware profile, configuration.
- Zero LLM / Ollama implementation (Pre-Phase-5 infrastructure only).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import threading


class ModelType(str, Enum):
    EMBEDDING = "EMBEDDING"
    RERANKER = "RERANKER"
    LLM = "LLM"
    MULTIMODAL = "MULTIMODAL"


class ModelReadiness(str, Enum):
    UNAVAILABLE = "unavailable"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    LOADING = "loading"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class ModelInfo:
    """Detailed provenance and runtime metadata for an AI / retrieval model."""
    model_id: str
    model_type: ModelType
    provider: str  # e.g. "fastembed", "onnx", "local"
    name: str  # e.g. "sentence-transformers/all-MiniLM-L6-v2"
    version: str = "1.0.0"  # Authoritative model/package version
    dimension: Optional[int] = None  # e.g. 384 for embedding models
    hardware_profile: str = "cpu"  # "cpu", "gpu", "npu"
    config: Dict[str, Any] = field(default_factory=dict)
    readiness: ModelReadiness = ModelReadiness.UNAVAILABLE
    error: Optional[str] = None
    is_active: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_type": self.model_type.value,
            "provider": self.provider,
            "name": self.name,
            "version": self.version,
            "dimension": self.dimension,
            "hardware_profile": self.hardware_profile,
            "config": self.config,
            "readiness": self.readiness.value,
            "error": self.error,
            "is_active": self.is_active,
        }


class ModelRegistry:
    """Thread-safe catalog of registered AI and retrieval models."""

    def __init__(self):
        self._models: Dict[str, ModelInfo] = {}
        self._lock = threading.Lock()

    def register_model(self, model: ModelInfo) -> None:
        """Registers or updates a model in the catalog."""
        with self._lock:
            self._models[model.model_id] = model

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        """Retrieves a model by its identifier."""
        with self._lock:
            return self._models.get(model_id)

    def get_active_model(self, model_type: ModelType) -> Optional[ModelInfo]:
        """Returns the currently active model for a specific model type."""
        with self._lock:
            for m in self._models.values():
                if m.model_type == model_type and m.is_active:
                    return m
            return None

    def set_active_model(self, model_id: str) -> None:
        """Activates a model and deactivates others of the same type."""
        with self._lock:
            target = self._models.get(model_id)
            if not target:
                raise ValueError(f"Model ID '{model_id}' is not registered.")
            for m in self._models.values():
                if m.model_type == target.model_type:
                    m.is_active = (m.model_id == model_id)

    def update_readiness(
        self,
        model_id: str,
        readiness: ModelReadiness,
        error: Optional[str] = None,
    ) -> None:
        """Updates the readiness lifecycle state of a model."""
        with self._lock:
            model = self._models.get(model_id)
            if model:
                model.readiness = readiness
                model.error = error

    def list_models(self, model_type: Optional[ModelType] = None) -> List[ModelInfo]:
        """Returns all registered models, optionally filtered by type."""
        with self._lock:
            if model_type is None:
                return list(self._models.values())
            return [m for m in self._models.values() if m.model_type == model_type]


# Global authoritative model registry initialized with default Phase 3 & 4 models.
#
# NOTE: readiness is intentionally registered as UNAVAILABLE, not READY. Both
# EmbeddingEngine and Reranker use deferred lazy loading (see embeddings.py /
# reranker.py) — the actual FastEmbed model is only loaded into memory on the
# first real call to _ensure_loaded(), which then transitions this registry
# entry through LOADING -> READY (or FAILED). Registering as READY at import
# time would make /ai/status report a false "ready" state for a model that
# has not been instantiated yet, defeating the purpose of the readiness state
# machine (it would look identical to a freshly-loaded, verified-working
# model to anyone consuming /ai/status).
default_model_registry = ModelRegistry()

default_model_registry.register_model(
    ModelInfo(
        model_id="fastembed:sentence-transformers/all-MiniLM-L6-v2",
        model_type=ModelType.EMBEDDING,
        provider="fastembed",
        name="sentence-transformers/all-MiniLM-L6-v2",
        version="1.0.0",
        dimension=384,
        hardware_profile="cpu",
        readiness=ModelReadiness.UNAVAILABLE,
        is_active=True,
    )
)

default_model_registry.register_model(
    ModelInfo(
        model_id="fastembed:BAAI/bge-reranker-base",
        model_type=ModelType.RERANKER,
        provider="fastembed",
        name="BAAI/bge-reranker-base",
        version="1.0.0",
        dimension=None,
        hardware_profile="cpu",
        readiness=ModelReadiness.UNAVAILABLE,
        is_active=True,
    )
)
