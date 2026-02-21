"""Port: repository fetcher — defined by the domain, implemented by infrastructure."""

from __future__ import annotations

from typing import Protocol

from repo_summarizer.domain.entities import FileNode, RepoMetadata
from repo_summarizer.domain.value_objects import GitHubUrl


class RepoFetcher(Protocol):
    """Abstract contract for fetching GitHub repository data."""

    async def fetch_metadata(self, url: GitHubUrl) -> RepoMetadata:
        """Return high-level repository metadata."""
        ...

    async def fetch_tree(self, url: GitHubUrl, branch: str) -> list[FileNode]:
        """Return the recursive file tree for the given branch."""
        ...

    async def fetch_file_content(self, url: GitHubUrl, path: str, branch: str) -> str:
        """Return the decoded text content of a single file."""
        ...

    async def fetch_languages(self, url: GitHubUrl) -> dict[str, int]:
        """Return language → byte-count mapping from the GitHub Languages API."""
        ...
