"""File filtering — decide which files to keep and how to classify them."""

from __future__ import annotations

from repo_summarizer.domain.entities import FileCategory, FileNode

SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        "out",
        "venv",
        ".venv",
        "env",
        "__pycache__",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "vendor",
        ".idea",
        ".vscode",
        ".next",
        ".nuxt",
        "coverage",
        ".coverage",
        "htmlcov",
        ".eggs",
        "target",           # Rust / Java
        "Pods",             # iOS
        ".gradle",
        ".terraform",
    }
)

SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pyc", ".pyo", ".so", ".o", ".a", ".dylib",
        ".dll", ".exe", ".bin", ".class", ".jar",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
        ".webp", ".mp3", ".mp4", ".avi", ".mov", ".wav",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".lock",
        ".min.js", ".min.css", ".map",
        ".DS_Store",
    }
)

SKIP_FILENAMES: frozenset[str] = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
        ".gitattributes",
        ".editorconfig",
        "yarn.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "Pipfile.lock",
        "poetry.lock",
        "composer.lock",
        "Gemfile.lock",
        "Cargo.lock",
    }
)

SECRET_FILES: frozenset[str] = frozenset(
    {".env", ".env.local", ".env.production", ".env.development"}
)

README_NAMES: frozenset[str] = frozenset(
    {"readme.md", "readme.rst", "readme.txt", "readme"}
)

CONFIG_NAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml", "setup.py", "setup.cfg",
        "package.json", "tsconfig.json", "webpack.config.js", "vite.config.ts",
        "requirements.txt", "requirements.in",
        "Pipfile", "Cargo.toml", "go.mod", "go.sum",
        "Gemfile", "build.gradle", "pom.xml",
        "Makefile", "CMakeLists.txt", "Justfile",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        ".env.example",
        "tox.ini", ".flake8", "ruff.toml", ".prettierrc",
    }
)

ENTRY_POINT_NAMES: frozenset[str] = frozenset(
    {
        "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py",
        "index.js", "index.ts", "index.tsx",
        "server.py", "server.js", "server.ts",
        "cli.py", "cli.js",
        "main.go", "main.rs", "main.c", "main.cpp",
        "Program.cs",
    }
)

TEST_INDICATORS: tuple[str, ...] = (
    "test_", "_test.", ".test.", "tests/", "spec/", "__tests__/",
)

DOCS_INDICATORS: tuple[str, ...] = (
    "docs/", "doc/", "documentation/",
)


def _segment_in_skip_dirs(path: str) -> bool:
    """Return *True* if any path segment belongs to ``SKIP_DIRS``."""
    parts = path.split("/")
    return any(
        part in SKIP_DIRS or part.endswith(".egg-info")
        for part in parts
    )


def _has_skip_extension(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in SKIP_EXTENSIONS)


def _filename(path: str) -> str:
    return path.rsplit("/", maxsplit=1)[-1]


def should_skip(node: FileNode, max_size_kb: int = 200) -> bool:
    """Return *True* if the node should be excluded from processing."""
    if node.type != "blob":
        return True

    path_lower = node.path.lower()
    name = _filename(path_lower)

    if name in SECRET_FILES:
        return True
    if name in SKIP_FILENAMES:
        return True
    if _segment_in_skip_dirs(node.path):
        return True
    if _has_skip_extension(path_lower):
        return True
    if node.size > max_size_kb * 1024:
        return True

    return False


def classify(path: str) -> FileCategory:
    """Assign a :class:`FileCategory` based on file name / path heuristics."""
    name_lower = _filename(path).lower()
    path_lower = path.lower()

    if name_lower in README_NAMES:
        return FileCategory.README
    if name_lower in CONFIG_NAMES:
        return FileCategory.CONFIG
    if name_lower in ENTRY_POINT_NAMES:
        return FileCategory.ENTRY_POINT
    if any(ind in path_lower for ind in TEST_INDICATORS):
        return FileCategory.TEST
    if any(ind in path_lower for ind in DOCS_INDICATORS):
        return FileCategory.DOCS

    return FileCategory.SOURCE


def filter_and_classify(
    nodes: list[FileNode],
    max_size_kb: int = 200,
) -> list[tuple[FileNode, FileCategory]]:
    """Filter the raw tree and return (node, category) pairs for relevant files."""
    results: list[tuple[FileNode, FileCategory]] = []
    for node in nodes:
        if should_skip(node, max_size_kb):
            continue
        results.append((node, classify(node.path)))
    return results
