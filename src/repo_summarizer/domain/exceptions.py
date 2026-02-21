"""Domain exception hierarchy."""

from __future__ import annotations


class RepoSummarizerError(Exception):
    """Base exception for the entire application."""


class InvalidGitHubUrlError(RepoSummarizerError):
    """The supplied URL does not point to a valid GitHub repository."""


class RepositoryNotFoundError(RepoSummarizerError):
    """The repository does not exist or is not accessible (404)."""


class RepositoryAccessDeniedError(RepoSummarizerError):
    """Access to the repository was denied (403)."""


class EmptyRepositoryError(RepoSummarizerError):
    """The repository exists but has no content (empty tree)."""


class GitHubRateLimitError(RepoSummarizerError):
    """GitHub API rate limit exceeded (429 / 403 with rate-limit header)."""


class LlmError(RepoSummarizerError):
    """Any error originating from the LLM provider."""


class ContentExtractionError(RepoSummarizerError):
    """Failed to extract or process repository content."""
