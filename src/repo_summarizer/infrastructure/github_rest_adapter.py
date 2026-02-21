"""GitHub REST API adapter — implements the RepoFetcher port."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from repo_summarizer.domain.entities import FileNode, RepoMetadata
from repo_summarizer.domain.exceptions import (
    ContentExtractionError,
    EmptyRepositoryError,
    GitHubRateLimitError,
    RepositoryAccessDeniedError,
    RepositoryNotFoundError,
)
from repo_summarizer.domain.value_objects import GitHubUrl

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"


class GitHubRestAdapter:
    """Concrete RepoFetcher backed by the GitHub v3 REST API."""

    def __init__(self, client: httpx.AsyncClient, token: str | None = None) -> None:
        self._client = client
        self._api_headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "repo-summarizer/1.0",
        }
        if token:
            self._api_headers["Authorization"] = f"Bearer {token}"

    async def fetch_metadata(self, url: GitHubUrl) -> RepoMetadata:
        """GET /repos/{owner}/{repo} → RepoMetadata."""
        resp = await self._api_get(f"/repos/{url.owner}/{url.repo}")
        data = resp.json()
        return RepoMetadata(
            owner=url.owner,
            repo=url.repo,
            default_branch=data.get("default_branch", "main"),
            description=data.get("description"),
        )

    async def fetch_tree(self, url: GitHubUrl, branch: str) -> list[FileNode]:
        """GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1 → [FileNode]."""
        resp = await self._api_get(
            f"/repos/{url.owner}/{url.repo}/git/trees/{branch}",
            params={"recursive": "1"},
        )
        data = resp.json()
        tree = data.get("tree", [])

        if not tree:
            raise EmptyRepositoryError(f"Repository {url.full_name} appears empty.")

        return [
            FileNode(
                path=item["path"],
                type=item.get("type", "blob"),
                size=item.get("size", 0),
            )
            for item in tree
        ]

    async def fetch_languages(self, url: GitHubUrl) -> dict[str, int]:
        """GET /repos/{owner}/{repo}/languages → {lang: bytes}."""
        try:
            resp = await self._api_get(f"/repos/{url.owner}/{url.repo}/languages")
            data: dict[str, int] = resp.json()
            return data
        except Exception:
            logger.debug("Failed to fetch languages for %s — returning empty", url.full_name)
            return {}

    async def fetch_file_content(
        self, url: GitHubUrl, path: str, branch: str
    ) -> str:
        """Fetch raw file content via raw.githubusercontent.com (no rate limit)."""
        raw_url = f"{_RAW_BASE}/{url.owner}/{url.repo}/{branch}/{path}"
        try:
            resp = await self._client.get(
                raw_url,
                headers={"User-Agent": "repo-summarizer/1.0"},
            )
        except httpx.HTTPError as exc:
            raise ContentExtractionError(
                f"Network error fetching {raw_url}: {exc}"
            ) from exc

        if resp.status_code == 200:
            return resp.text

        if resp.status_code == 404:
            raise ContentExtractionError(f"File not found: {path}")

        raise ContentExtractionError(
            f"raw.githubusercontent.com returned HTTP {resp.status_code} for {path}"
        )

    async def _api_get(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Perform a GitHub API GET request with error translation."""
        url = f"{_GITHUB_API}{endpoint}"
        try:
            resp = await self._client.get(
                url, headers=self._api_headers, params=params
            )
        except httpx.HTTPError as exc:
            raise ContentExtractionError(
                f"Network error fetching {url}: {exc}"
            ) from exc

        if resp.status_code == 200:
            return resp

        if resp.status_code == 404:
            raise RepositoryNotFoundError(
                "Repository not found. Make sure the URL points to a public repository."
            )

        if resp.status_code == 403:
            remaining = resp.headers.get("x-ratelimit-remaining", "")
            if remaining == "0":
                reset_raw = resp.headers.get("x-ratelimit-reset", "")
                try:
                    reset_str = datetime.fromtimestamp(int(reset_raw), tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    )
                except (ValueError, OSError):
                    reset_str = reset_raw or "unknown"
                raise GitHubRateLimitError(
                    f"GitHub API rate limit exceeded. Resets at {reset_str}. "
                    "Set the GITHUB_TOKEN environment variable to increase the limit."
                )
            raise RepositoryAccessDeniedError(
                "Access denied. The repository may be private."
            )

        if resp.status_code == 429:
            raise GitHubRateLimitError("GitHub API rate limit exceeded (HTTP 429).")

        raise ContentExtractionError(
            f"GitHub API returned HTTP {resp.status_code} for {url}"
        )
