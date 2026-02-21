"""Pydantic request / response DTOs for the API boundary."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class SummarizeRequest(BaseModel):
    """Request body for ``POST /summarize``."""

    github_url: str

    @field_validator("github_url")
    @classmethod
    def _must_be_github(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            msg = "github_url must not be empty."
            raise ValueError(msg)
        if "github.com" not in stripped.lower():
            msg = (
                f"Invalid URL: '{stripped}'. "
                "Only public GitHub repository URLs are supported."
            )
            raise ValueError(msg)
        return stripped


class SummarizeResponse(BaseModel):
    """Successful response from ``POST /summarize``."""

    summary: str
    technologies: list[str]
    structure: str


class ErrorResponse(BaseModel):
    """Standard error envelope returned on all failure paths."""

    status: str = "error"
    message: str
