"""
Model Management & Readiness Router for FileMind .
"""

from typing import Any, Dict, List, Optional
import urllib.request
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.ollama_provider import check_ollama_readiness, default_ollama_provider
from app.core.context import AppContext
from app.core.deps import get_app_context
from app.schemas import InstalledModelItem, ModelSelectionRequest, ModelStatusResponse

logger = logging.getLogger("FileMind.AI.ModelsRouter")

router = APIRouter(prefix="/api/models", tags=["Models"])


@router.get("/status", response_model=ModelStatusResponse)
def get_model_status(
    ctx: AppContext = Depends(get_app_context),
) -> ModelStatusResponse:
    """Detects Ollama health, active generation model, active embedding model, and installed models."""
    readiness = check_ollama_readiness(
        endpoint=default_ollama_provider.endpoint,
        model=default_ollama_provider.model,
    )

    installed_models = []
    if readiness.is_ollama_online:
        try:
            req = urllib.request.Request(
                f"{default_ollama_provider.endpoint}/api/tags",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models_raw = data.get("models") or []
                for m in models_raw:
                    name = m.get("name", "")
                    details = m.get("details") or {}
                    param_size = details.get("parameter_size")
                    is_rec = any(rec in name.lower() for rec in ["qwen", "llama3", "mistral", "phi3", "deepseek"])
                    installed_models.append(
                        InstalledModelItem(
                            name=name,
                            size_bytes=m.get("size"),
                            digest=m.get("digest"),
                            modified_at=m.get("modified_at"),
                            is_recommended=is_rec,
                            parameter_size=param_size,
                        )
                    )
        except Exception as exc:
            logger.warning("Could not list local Ollama models: %s", exc)

    status_msg = "Ready" if (readiness.is_ollama_online and readiness.has_default_model) else (
        "Ollama online (model missing)" if readiness.is_ollama_online else "Ollama offline"
    )

    return ModelStatusResponse(
        is_ollama_online=readiness.is_ollama_online,
        active_generation_model=default_ollama_provider.model,
        active_embedding_model="all-minilm (384-dim)",
        available_models=installed_models,
        endpoint=default_ollama_provider.endpoint,
        status_message=status_msg,
    )


@router.post("/select", response_model=ModelStatusResponse)
def select_model(
    req: ModelSelectionRequest,
    ctx: AppContext = Depends(get_app_context),
) -> ModelStatusResponse:
    """Switches the active generation model for local AI."""
    if req.generation_model:
        clean_model = req.generation_model.strip()
        default_ollama_provider.model = clean_model
        logger.info("Switched active generation model to: %s", clean_model)

    return get_model_status(ctx=ctx)
