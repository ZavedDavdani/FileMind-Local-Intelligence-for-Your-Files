"""Centralized service exception translation and error handling for FileMind API."""

from __future__ import annotations

import functools
import logging
from typing import Callable, Optional, TypeVar

from fastapi import HTTPException, status

F = TypeVar("F", bound=Callable)


def map_service_errors(
    logger: logging.Logger,
    action_description: str,
    custom_500_detail: Optional[str] = None,
) -> Callable[[F], F]:
    """Decorator mapping standard domain/service exceptions to deterministic HTTP status codes.

    Preserves exact error semantics:
      - ValueError -> 404 NOT FOUND with exception message
      - RuntimeError -> 409 CONFLICT with exception message
      - HTTPException -> re-raised unchanged
      - Unexpected Exception -> 500 INTERNAL SERVER ERROR with logged error message
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
            except RuntimeError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("%s error: %s", action_description, exc)
                detail_msg = custom_500_detail or f"An error occurred while {action_description.lower()}."
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=detail_msg,
                )

        return wrapper

    return decorator
