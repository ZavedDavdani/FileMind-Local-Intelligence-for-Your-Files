"""Tests for generation busy error handling, concurrency, and model initialization."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ai.generation import (
    GenerationStatus,
    GroundedGenerationResponse,
    GroundedGenerationService,
)
from app.ai.generation_coordinator import (
    LocalGenerationBusyError,
    LocalGenerationCoordinator,
)
from app.ai.context import BoundedContextPackage, BudgetAccounting, EvidenceStatus
from app.main import app


def test_generation_service_busy_handling():
    """Verifies that LocalGenerationBusyError produces an explicit user-friendly response."""
    busy_coord = LocalGenerationCoordinator(capacity=1)
    svc = GroundedGenerationService(generation_coordinator=busy_coord)

    # Acquire the single slot
    with busy_coord.acquire():
        # Second call while slot is busy
        pkg = BoundedContextPackage(
            status=EvidenceStatus.READY,
            items=[],
            budget=BudgetAccounting(
                total_budget=4096,
                system_reserved=500,
                output_reserved=1000,
                evidence_budget=2596,
                evidence_used=100,
                evidence_remaining=2496,
                candidates_considered=1,
                candidates_included=1,
                candidates_omitted=0,
                omitted_candidates=[],
            ),
        )
        # Note: If pkg has items or status READY, but slot is busy, generate_answer catches LocalGenerationBusyError
        pkg.items = [MagicMock()]
        resp = svc.generate_answer(query="What is this?", context_package=pkg)
        assert resp.generation_status == GenerationStatus.GENERATION_FAILED
        assert "already in progress" in (resp.error or "")
        assert "already in progress" in resp.answer


def test_ask_route_concurrency_409():
    """Verifies that /ai/ask returns HTTP 409 Conflict if LocalGenerationBusyError escapes."""
    client = TestClient(app)
    from app.ai import default_ask_service

    with patch.object(default_ask_service, "ask", side_effect=LocalGenerationBusyError("A local AI generation is already in progress")):
        response = client.post("/ai/ask", json={"query": "test query"})
        assert response.status_code == 409
        assert "already in progress" in response.json()["detail"]
