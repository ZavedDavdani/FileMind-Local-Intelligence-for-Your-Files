"""Process-wide admission control for local Ollama generation."""

from contextlib import contextmanager
import threading
from typing import Iterator


class LocalGenerationBusyError(RuntimeError):
    """Raised when the single local generation slot is already in use."""


class LocalGenerationCoordinator:
    def __init__(self, capacity: int = 1):
        self._semaphore = threading.BoundedSemaphore(capacity)

    @contextmanager
    def acquire(self) -> Iterator[None]:
        if not self._semaphore.acquire(blocking=False):
            raise LocalGenerationBusyError("A local AI generation is already in progress")
        try:
            yield
        finally:
            self._semaphore.release()


default_generation_coordinator = LocalGenerationCoordinator(capacity=1)
