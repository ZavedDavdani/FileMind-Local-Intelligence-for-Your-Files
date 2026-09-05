"""
FileMind Grounded Local LLM Generation Service and Contracts.

Coordinates bounded context, deterministic grounded prompt construction, local Ollama generation,
and citation validation into an authoritative, local-only grounded question-answering pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Protocol

from app.ai.citation import CitationValidator
from app.ai.generation_coordinator import (
    LocalGenerationBusyError,
    default_generation_coordinator,
)
from app.ai.context import (
    BoundedContextPackage,
    BudgetAccounting,
    EvidenceStatus,
    TokenEstimator,
)
from app.ai.ollama_provider import (
    OllamaConnectionError,
    OllamaError,
    OllamaGenerationError,
    OllamaProvider,
    OllamaResponse,
    OllamaTimeoutError,
)
from app.ai.prompt import (
    CitationSource,
    GroundedPrompt,
    PromptBuilder,
    default_prompt_builder,
)
from app.core.config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger("FileMind.AI.Generation")


class GenerationStatus(str, Enum):
    """Reflects the outcome of grounded LLM generation."""
    READY = "READY"                          # Generated answer successfully grounded in evidence
    NO_EVIDENCE = "NO_EVIDENCE"              # Zero evidence available; LLM intentionally not called
    BUDGET_LIMITED = "BUDGET_LIMITED"        # Generation completed on budget-restricted evidence subset
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"  # Local Ollama daemon unreachable or model not installed
    TIMEOUT = "TIMEOUT"                      # Generation exceeded configured read timeout
    GENERATION_FAILED = "GENERATION_FAILED"  # Provider error or HTTP non-200
    INVALID_RESPONSE = "INVALID_RESPONSE"    # Empty, unparseable, or invalid model response


@dataclass(frozen=True)
class ModelIdentity:
    """Explicit identification of the local generation model and provider."""
    provider: str = "ollama"
    model_name: str = OLLAMA_MODEL
    is_local: bool = True
    model_tag: Optional[str] = OLLAMA_MODEL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "is_local": self.is_local,
            "model_tag": self.model_tag,
        }


@dataclass(frozen=True)
class GenerationConfig:
    """Configurable execution parameters for grounded generation."""
    temperature: float = 0.1  # Conservative low temperature for factual grounding
    max_output_tokens: int = 1000
    request_timeout: float = 120.0

    def __post_init__(self):
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError("Temperature must be between 0.0 and 2.0")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be positive")


class BaseLLMProvider(Protocol):
    """Protocol satisfied by OllamaProvider and test fake providers."""
    def generate(self, prompt: str, **kwargs: Any) -> OllamaResponse:
        ...


@dataclass
class GroundedGenerationRequest:
    """Request payload for grounded generation."""
    query: str
    context_package: BoundedContextPackage
    config: Optional[GenerationConfig] = None
    history: Optional[List[Dict[str, str]]] = None


@dataclass
class GroundedGenerationResponse:
    """Authoritative response contract returned by the grounded generation pipeline."""
    answer: str
    query: str
    generation_status: GenerationStatus
    evidence_status: EvidenceStatus
    citations: List[CitationSource]
    unresolved_citations: List[str]
    model_identity: ModelIdentity
    prompt_tokens_estimated: int
    context_budget: BudgetAccounting
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "query": self.query,
            "generation_status": self.generation_status.value,
            "evidence_status": self.evidence_status.value,
            "citations": [c.to_dict() for c in self.citations],
            "unresolved_citations": self.unresolved_citations,
            "model_identity": self.model_identity.to_dict(),
            "prompt_tokens_estimated": self.prompt_tokens_estimated,
            "context_budget": self.context_budget.to_dict(),
            "error": self.error,
        }


class GroundedGenerationService:
    """
    Coordinates grounded prompt construction, local Ollama execution, and citation validation.
    """

    def __init__(
        self,
        provider: Optional[BaseLLMProvider] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        generation_coordinator: Optional[Any] = None,
    ):
        self.provider = provider or OllamaProvider()
        self.prompt_builder = prompt_builder or default_prompt_builder
        self.generation_coordinator = generation_coordinator or default_generation_coordinator

    def generate_answer(
        self,
        query: str,
        context_package: BoundedContextPackage,
        config: Optional[GenerationConfig] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> GroundedGenerationResponse:
        """
        Executes grounded generation from query and bounded evidence.
        Enforces no-evidence short-circuiting, timeout handling, and citation validation.
        """
        gen_cfg = config or GenerationConfig()
        model_id = ModelIdentity(
            provider="ollama",
            model_name=getattr(self.provider, "model", OLLAMA_MODEL),
            is_local=True,
            model_tag=getattr(self.provider, "model", OLLAMA_MODEL),
        )

        # 1. Critical Grounding Guard: If NO_EVIDENCE, never call LLM
        if context_package.status == EvidenceStatus.NO_EVIDENCE or len(context_package.items) == 0:
            logger.info("No evidence available for query; short-circuiting LLM generation.")
            return GroundedGenerationResponse(
                answer="The indexed files do not contain sufficient evidence to answer this question.",
                query=query.strip(),
                generation_status=GenerationStatus.NO_EVIDENCE,
                evidence_status=EvidenceStatus.NO_EVIDENCE,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=0,
                context_budget=context_package.budget,
                error=None,
            )

        # 2. Build Grounded Prompt
        try:
            prompt: GroundedPrompt = self.prompt_builder.build_prompt(query, context_package, history=history)
        except Exception as exc:
            logger.error("Failed to construct grounded prompt: %s", exc)
            return GroundedGenerationResponse(
                answer="",
                query=query,
                generation_status=GenerationStatus.GENERATION_FAILED,
                evidence_status=context_package.status,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=0,
                context_budget=context_package.budget,
                error=f"Prompt construction error: {exc}",
            )

        # 3. Invoke Local Provider
        try:
            with self.generation_coordinator.acquire():
                try:
                    response: OllamaResponse = self.provider.generate(
                        prompt.full_prompt,
                        temperature=gen_cfg.temperature,
                    )
                except TypeError as te:
                    if "temperature" in str(te) or "unexpected keyword argument" in str(te):
                        response = self.provider.generate(prompt.full_prompt)
                    else:
                        raise
        except OllamaConnectionError as exc:
            logger.warning("Local Ollama endpoint unreachable: %s", exc)
            return GroundedGenerationResponse(
                answer="",
                query=query,
                generation_status=GenerationStatus.MODEL_UNAVAILABLE,
                evidence_status=context_package.status,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=prompt.estimated_tokens,
                context_budget=context_package.budget,
                error=str(exc),
            )
        except OllamaTimeoutError as exc:
            logger.warning("Local Ollama request timed out: %s", exc)
            return GroundedGenerationResponse(
                answer="",
                query=query,
                generation_status=GenerationStatus.TIMEOUT,
                evidence_status=context_package.status,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=prompt.estimated_tokens,
                context_budget=context_package.budget,
                error=str(exc),
            )
        except LocalGenerationBusyError as exc:
            logger.info("Local generation slot busy: %s", exc)
            return GroundedGenerationResponse(
                answer="A local AI generation is already in progress. Please try again in a moment.",
                query=query,
                generation_status=GenerationStatus.GENERATION_FAILED,
                evidence_status=context_package.status,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=prompt.estimated_tokens,
                context_budget=context_package.budget,
                error=str(exc),
            )
        except OllamaGenerationError as exc:
            logger.error("Local Ollama generation error: %s", exc)
            return GroundedGenerationResponse(
                answer="",
                query=query,
                generation_status=GenerationStatus.GENERATION_FAILED,
                evidence_status=context_package.status,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=prompt.estimated_tokens,
                context_budget=context_package.budget,
                error=str(exc),
            )
        except Exception as exc:
            logger.error("Unexpected generation failure: %s", exc)
            return GroundedGenerationResponse(
                answer="",
                query=query,
                generation_status=GenerationStatus.GENERATION_FAILED,
                evidence_status=context_package.status,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=prompt.estimated_tokens,
                context_budget=context_package.budget,
                error=f"Unexpected error: {exc}",
            )

        # 4. Validate Output and Citations
        raw_answer = response.response.strip()
        if not raw_answer:
            return GroundedGenerationResponse(
                answer="",
                query=query,
                generation_status=GenerationStatus.INVALID_RESPONSE,
                evidence_status=context_package.status,
                citations=[],
                unresolved_citations=[],
                model_identity=model_id,
                prompt_tokens_estimated=prompt.estimated_tokens,
                context_budget=context_package.budget,
                error="Model returned an empty response.",
            )

        val_result = CitationValidator.extract_and_validate(raw_answer, prompt.citation_map)

        gen_status = (
            GenerationStatus.BUDGET_LIMITED
            if context_package.status == EvidenceStatus.BUDGET_LIMITED
            else GenerationStatus.READY
        )

        return GroundedGenerationResponse(
            answer=raw_answer,
            query=query,
            generation_status=gen_status,
            evidence_status=context_package.status,
            citations=val_result.valid_citations,
            unresolved_citations=val_result.unresolved_citation_ids,
            model_identity=model_id,
            prompt_tokens_estimated=prompt.estimated_tokens,
            context_budget=context_package.budget,
            error=None,
        )


# Global default generation service instance
default_generation_service = GroundedGenerationService()
