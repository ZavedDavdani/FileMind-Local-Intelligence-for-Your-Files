"""Application runtime dependency context for FileMind.

Provides an explicit, application-scoped container holding shared runtime dependencies:
- db_manager (DatabaseManager)
- embedding_engine (EmbeddingEngine)
- reranker (Reranker)
- model_registry (ModelRegistry)
- generation_coordinator (LocalGenerationCoordinator)
- engine_coordinator (EngineCoordinator)
"""

import sys
from typing import Optional

from app.ai.generation_coordinator import (
    LocalGenerationCoordinator,
    default_generation_coordinator,
)
from app.db.connection import DatabaseManager, db_manager
from app.engine.coordinator import EngineCoordinator, coordinator
from app.retrieval.embeddings import EmbeddingEngine, default_embedding_engine
from app.retrieval.model_registry import ModelRegistry, default_model_registry
from app.retrieval.reranker import Reranker, default_reranker


class AppContext:
    """Application-scoped dependency context for FileMind."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        embedding_engine: Optional[EmbeddingEngine] = None,
        reranker: Optional[Reranker] = None,
        model_registry: Optional[ModelRegistry] = None,
        generation_coordinator: Optional[LocalGenerationCoordinator] = None,
        engine_coordinator: Optional[EngineCoordinator] = None,
    ):
        self._db_manager = db_manager
        self._embedding_engine = embedding_engine
        self._reranker = reranker
        self._model_registry = model_registry
        self._generation_coordinator = generation_coordinator
        self._engine_coordinator = engine_coordinator

    @property
    def db_manager(self) -> DatabaseManager:
        if self._db_manager is not None:
            return self._db_manager
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "db_manager") and main_mod.db_manager is not None:
            return main_mod.db_manager
        return db_manager

    @db_manager.setter
    def db_manager(self, value: Optional[DatabaseManager]) -> None:
        self._db_manager = value

    @property
    def embedding_engine(self) -> EmbeddingEngine:
        if self._embedding_engine is not None:
            return self._embedding_engine
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "embedding_engine") and main_mod.embedding_engine is not None:
            return main_mod.embedding_engine
        return default_embedding_engine

    @embedding_engine.setter
    def embedding_engine(self, value: Optional[EmbeddingEngine]) -> None:
        self._embedding_engine = value

    @property
    def reranker(self) -> Reranker:
        if self._reranker is not None:
            return self._reranker
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "reranker") and main_mod.reranker is not None:
            return main_mod.reranker
        return default_reranker

    @reranker.setter
    def reranker(self, value: Optional[Reranker]) -> None:
        self._reranker = value

    @property
    def model_registry(self) -> ModelRegistry:
        if self._model_registry is not None:
            return self._model_registry
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "model_registry") and main_mod.model_registry is not None:
            return main_mod.model_registry
        return default_model_registry

    @model_registry.setter
    def model_registry(self, value: Optional[ModelRegistry]) -> None:
        self._model_registry = value

    @property
    def generation_coordinator(self) -> LocalGenerationCoordinator:
        if self._generation_coordinator is not None:
            return self._generation_coordinator
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "generation_coordinator") and main_mod.generation_coordinator is not None:
            return main_mod.generation_coordinator
        return default_generation_coordinator

    @generation_coordinator.setter
    def generation_coordinator(self, value: Optional[LocalGenerationCoordinator]) -> None:
        self._generation_coordinator = value

    @property
    def engine_coordinator(self) -> EngineCoordinator:
        if self._engine_coordinator is not None:
            return self._engine_coordinator
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "coordinator") and main_mod.coordinator is not None:
            return main_mod.coordinator
        return coordinator

    @engine_coordinator.setter
    def engine_coordinator(self, value: Optional[EngineCoordinator]) -> None:
        self._engine_coordinator = value

    @property
    def ollama_provider(self):
        from app.ai.ollama_provider import OllamaProvider
        return OllamaProvider()

    def close(self) -> None:
        """Gracefully closes coordinators and resources."""
        if self._engine_coordinator is not None:
            try:
                self._engine_coordinator.shutdown()
            except Exception:
                pass


# Global default instance wrapping the authoritative runtime singletons
default_app_context = AppContext()
