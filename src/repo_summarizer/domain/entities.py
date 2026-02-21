"""Domain entities — pure data structures with no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FileCategory(str, Enum):
    """Classification bucket for repository files."""

    README = "readme"
    CONFIG = "config"
    ENTRY_POINT = "entry_point"
    SOURCE = "source"
    TEST = "test"
    DOCS = "docs"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class FileNode:
    """A single node from the GitHub tree API (blob or sub-tree)."""

    path: str
    type: str  # "blob" or "tree"
    size: int = 0


@dataclass(frozen=True, slots=True)
class RepoMetadata:
    """High-level metadata about a GitHub repository."""

    owner: str
    repo: str
    default_branch: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class RepoFile:
    """A fetched file with its decoded content."""

    path: str
    content: str
    size_bytes: int
    language: str = "unknown"
    category: FileCategory = FileCategory.SOURCE


@dataclass(frozen=True, slots=True)
class FileSkeletonResult:
    """Result of AST skeleton extraction for a single file."""

    path: str
    skeleton_text: str
    imports: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ScoredFile:
    """A file annotated with its composite importance score."""

    path: str
    score: float
    category: FileCategory


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """The final structured output returned to the caller."""

    summary: str
    technologies: list[str]
    structure: str
