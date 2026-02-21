"""FastAPI dependency injection wiring."""

from __future__ import annotations

from functools import lru_cache

import httpx

from repo_summarizer.infrastructure.config import Settings, get_settings
from repo_summarizer.infrastructure.github_rest_adapter import GitHubRestAdapter
from repo_summarizer.infrastructure.openai_adapter import OpenAIAdapter
from repo_summarizer.services.summarize_repo import SummarizeRepoUseCase

_http_client: httpx.AsyncClient | None = None
_openai_adapter: OpenAIAdapter | None = None


async def startup() -> None:
    """Initialise shared resources — called from the lifespan context manager."""
    global _http_client, _openai_adapter  # noqa: PLW0603

    settings = get_settings()
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    _openai_adapter = OpenAIAdapter(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
    )


async def shutdown() -> None:
    """Release shared resources."""
    global _http_client, _openai_adapter  # noqa: PLW0603

    if _http_client:
        await _http_client.aclose()
        _http_client = None
    if _openai_adapter:
        await _openai_adapter.close()
        _openai_adapter = None


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return get_settings()


def get_use_case() -> SummarizeRepoUseCase:
    """Build (or return cached) use-case with injected adapters."""
    settings = _settings()

    assert _http_client is not None, "startup() was not called"
    assert _openai_adapter is not None, "startup() was not called"

    token = settings.github_token.get_secret_value() if settings.github_token else None
    github_adapter = GitHubRestAdapter(client=_http_client, token=token)

    return SummarizeRepoUseCase(
        repo_fetcher=github_adapter,
        llm_gateway=_openai_adapter,
        max_context_tokens=settings.max_context_tokens,
        max_files_to_fetch=settings.max_files_to_fetch,
        max_file_size_kb=settings.max_file_size_kb,
    )
