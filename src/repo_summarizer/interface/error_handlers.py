"""Global exception handlers — translate domain errors to HTTP responses.

Each domain exception maps to a specific HTTP status code and the
standard ``{"status": "error", "message": "..."}`` envelope.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from repo_summarizer.domain.exceptions import (
    ContentExtractionError,
    EmptyRepositoryError,
    GitHubRateLimitError,
    InvalidGitHubUrlError,
    LlmError,
    RepoSummarizerError,
    RepositoryAccessDeniedError,
    RepositoryNotFoundError,
)

logger = logging.getLogger(__name__)

_EXCEPTION_STATUS: list[tuple[type[RepoSummarizerError], int]] = [
    (InvalidGitHubUrlError, 422),
    (RepositoryNotFoundError, 404),
    (RepositoryAccessDeniedError, 403),
    (EmptyRepositoryError, 422),
    (GitHubRateLimitError, 429),
    (LlmError, 502),
    (ContentExtractionError, 500),
]


def _error_json(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": message},
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach exception handlers to the FastAPI application."""

    # ── Domain exceptions ───────────────────────────────────────────────

    for exc_type, code in _EXCEPTION_STATUS:

        def _make_handler(
            status_code: int,
        ):  # type: ignore[no-untyped-def]
            async def handler(request: Request, exc: Exception) -> JSONResponse:
                logger.warning("%s: %s", type(exc).__name__, exc)
                return _error_json(status_code, str(exc))

            return handler

        app.add_exception_handler(exc_type, _make_handler(code))

    # ── Pydantic / FastAPI validation errors ────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        messages = []
        for err in exc.errors():
            loc = " → ".join(str(p) for p in err.get("loc", []))
            messages.append(f"{loc}: {err.get('msg', 'validation error')}")
        return _error_json(422, "; ".join(messages))

    # ── Catch-all for unexpected errors ─────────────────────────────────

    @app.exception_handler(Exception)
    async def generic_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception")
        return _error_json(500, "An unexpected error occurred. Please try again later.")
