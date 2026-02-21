"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from repo_summarizer.interface.dependencies import shutdown, startup
from repo_summarizer.interface.error_handlers import register_error_handlers
from repo_summarizer.interface.routes import router


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup / shutdown of shared resources."""
    await startup()
    yield
    await shutdown()


def create_app() -> FastAPI:
    """Build and wire the FastAPI application."""
    app = FastAPI(
        title="GitHub Repo Summarizer",
        version="1.0.0",
        description=(
            "Takes a public GitHub repository URL and returns a structured "
            "summary of the project: what it does, technologies used, and "
            "how it's structured."
        ),
        lifespan=_lifespan,
    )

    register_error_handlers(app)
    app.include_router(router)

    # ── Health check (simple liveness probe) ────────────────────────────

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
