"""Observability utilities, latency tracking, and standard degraded-state representations."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


class LatencyTracker:
    """Lightweight context manager for measuring elapsed execution latency in milliseconds."""

    def __init__(self, target_dict: Optional[Dict[str, float]] = None, key: Optional[str] = None):
        self.target_dict = target_dict
        self.key = key
        self.start_time: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> LatencyTracker:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *exc_info) -> None:
        self.elapsed_ms = round((time.perf_counter() - self.start_time) * 1000, 2)
        if self.target_dict is not None and self.key:
            self.target_dict[self.key] = self.elapsed_ms


def build_degraded_metadata(
    is_degraded: bool,
    reason: Optional[str] = None,
    latency_breakdown: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Builds a standard retrieval metadata payload preserving all schema fields."""
    return {
        "degraded": bool(is_degraded),
        "degraded_reason": reason if is_degraded else None,
        "latency_breakdown_ms": latency_breakdown or {},
    }
