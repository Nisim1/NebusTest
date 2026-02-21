"""Application configuration — loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from env vars (or ``.env`` file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr
    openai_model: str = "gpt-4o-mini"
    github_token: SecretStr | None = None
    max_context_tokens: int = 32_000
    max_file_size_kb: int = 200
    max_files_to_fetch: int = 30
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton application settings (cached after first call)."""
    return Settings()  # type: ignore[call-arg]
