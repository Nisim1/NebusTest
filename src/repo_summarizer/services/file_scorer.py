"""File importance scoring — heuristic + graph centrality hybrid.

Combines PageRank on the import graph with name/path/size heuristics to
produce a single composite score per file, allowing deterministic
prioritisation of the most informative files.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import networkx as nx  # type: ignore[import-untyped]

from repo_summarizer.domain.entities import FileCategory, FileSkeletonResult, ScoredFile

# ── Heuristic weight constants ──────────────────────────────────────────────

_CATEGORY_BONUS: dict[FileCategory, float] = {
    FileCategory.README: 1.0,
    FileCategory.CONFIG: 0.7,
    FileCategory.ENTRY_POINT: 0.9,
    FileCategory.SOURCE: 0.5,
    FileCategory.TEST: 0.3,
    FileCategory.DOCS: 0.4,
    FileCategory.OTHER: 0.1,
}

_ENTRY_POINT_NAMES = frozenset(
    {
        "main.py", "app.py", "index.js", "index.ts", "index.tsx",
        "server.py", "server.js", "server.ts", "manage.py",
        "cli.py", "wsgi.py", "asgi.py", "main.go", "main.rs",
    }
)


def _name_heuristic(path: str) -> float:
    """Score 0-1 based on how 'important' the filename looks."""
    name = path.rsplit("/", maxsplit=1)[-1].lower()
    if name in _ENTRY_POINT_NAMES:
        return 1.0
    if name.startswith("readme"):
        return 1.0
    if name in ("__init__.py", "mod.rs", "lib.rs"):
        return 0.6
    return 0.0


def _depth_score(path: str) -> float:
    """Shallower files score higher (root files ≈ 1.0)."""
    depth = path.count("/")
    return 1.0 / (1.0 + depth)


def _size_score(size_bytes: int) -> float:
    """Medium-sized files (1–20 KB) score highest."""
    if size_bytes <= 0:
        return 0.1
    kb = size_bytes / 1024
    if kb < 0.1:
        return 0.2
    if kb > 100:
        return 0.3
    # Bell-curve peaking around 5 KB
    return max(0.1, 1.0 - abs(math.log10(kb / 5)) * 0.3)


# ── Graph centrality ───────────────────────────────────────────────────────


def _build_import_graph(
    skeletons: Sequence[FileSkeletonResult],
) -> nx.DiGraph:  # type: ignore[type-arg]
    """Build a directed graph where edges represent import relationships."""
    graph: nx.DiGraph = nx.DiGraph()  # type: ignore[type-arg]

    # Map module-like names to file paths for resolution
    path_by_module: dict[str, str] = {}
    for sk in skeletons:
        # e.g. "src/foo/bar.py" → "bar", "foo.bar"
        parts = sk.path.replace("\\", "/").rsplit("/", maxsplit=1)
        name = parts[-1].rsplit(".", maxsplit=1)[0] if "." in parts[-1] else parts[-1]
        path_by_module[name] = sk.path
        graph.add_node(sk.path)

    for sk in skeletons:
        for imp in sk.imports:
            target = imp.split(".")[0]
            if target in path_by_module:
                target_path = path_by_module[target]
                if target_path != sk.path:
                    graph.add_edge(sk.path, target_path)

    return graph


def _compute_centrality(graph: nx.DiGraph) -> dict[str, float]:  # type: ignore[type-arg]
    """Return normalised PageRank scores (0-1) keyed by file path."""
    if graph.number_of_nodes() < 2:
        return {}

    try:
        raw: dict[str, float] = nx.pagerank(graph, alpha=0.85)  # type: ignore[assignment]
    except nx.NetworkXError:
        return {}

    max_val = max(raw.values()) if raw else 1.0
    if max_val == 0:
        return {k: 0.0 for k in raw}
    return {k: v / max_val for k, v in raw.items()}


# ── Public API ──────────────────────────────────────────────────────────────


def score_files(
    skeletons: Sequence[FileSkeletonResult],
    categories: Mapping[str, FileCategory],
    sizes: Mapping[str, int],
) -> list[ScoredFile]:
    """Return files sorted by descending composite importance score.

    Parameters
    ----------
    skeletons:
        AST extraction results (used to build the import graph).
    categories:
        ``{path: FileCategory}`` mapping produced by the file filter.
    sizes:
        ``{path: size_bytes}`` mapping from the tree.
    """
    graph = _build_import_graph(skeletons)
    centrality = _compute_centrality(graph)
    use_centrality = len(centrality) >= 3

    scored: list[ScoredFile] = []
    for sk in skeletons:
        cat = categories.get(sk.path, FileCategory.SOURCE)
        cat_bonus = _CATEGORY_BONUS.get(cat, 0.1)
        name_h = _name_heuristic(sk.path)
        depth_h = _depth_score(sk.path)
        size_h = _size_score(sizes.get(sk.path, 0))

        if use_centrality:
            cent = centrality.get(sk.path, 0.0)
            composite = (
                0.30 * cent
                + 0.25 * cat_bonus
                + 0.20 * name_h
                + 0.15 * depth_h
                + 0.10 * size_h
            )
        else:
            # Fallback: heuristic-only
            composite = (
                0.35 * cat_bonus
                + 0.30 * name_h
                + 0.20 * depth_h
                + 0.15 * size_h
            )

        scored.append(ScoredFile(path=sk.path, score=composite, category=cat))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
