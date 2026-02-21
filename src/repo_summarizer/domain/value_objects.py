"""Value objects — self-validating domain primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repo_summarizer.domain.exceptions import InvalidGitHubUrlError

_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9\-_.]+)/(?P<repo>[A-Za-z0-9\-_.]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True, slots=True)
class GitHubUrl:
    """Validated GitHub repository URL.

    Extracts *owner* and *repo* from a URL like
    ``https://github.com/psf/requests``.  Rejects anything that does not match
    the expected pattern.
    """

    owner: str
    repo: str
    raw: str

    @classmethod
    def from_string(cls, url: str) -> GitHubUrl:
        """Parse and validate a raw URL string."""
        url = url.strip()
        match = _GITHUB_URL_RE.match(url)
        if not match:
            raise InvalidGitHubUrlError(
                f"Invalid GitHub URL: '{url}'. "
                "Expected format: https://github.com/<owner>/<repo>"
            )
        return cls(owner=match["owner"], repo=match["repo"], raw=url)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"
