"""Summarize-repository use case — main orchestration pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from repo_summarizer.domain.entities import (
    FileCategory,
    FileNode,
    FileSkeletonResult,
    RepoFile,
    ScoredFile,
    SummaryResult,
)
from repo_summarizer.domain.exceptions import (
    ContentExtractionError,
    EmptyRepositoryError,
    LlmError,
)
from repo_summarizer.domain.ports.llm_gateway import LlmGateway
from repo_summarizer.domain.ports.repo_fetcher import RepoFetcher
from repo_summarizer.domain.value_objects import GitHubUrl
from repo_summarizer.services.ast_extractor import extract_skeleton
from repo_summarizer.services.content_assembler import assemble
from repo_summarizer.services.file_filter import filter_and_classify
from repo_summarizer.services.file_scorer import score_files
from repo_summarizer.services.security_sentinel import sanitize_batch
from repo_summarizer.services.token_budget import (
    BudgetedContent,
    allocate,
    count_tokens,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior software analyst. Given information about a GitHub \
repository (language breakdown, README, configuration files, directory \
tree, and AST skeletons of key source files), produce a structured JSON analysis.

Return **only** valid JSON with exactly these three keys:

{
  "summary": "<description>",
  "technologies": ["<lang>", "<framework>", ...],
  "structure": "<layout>"
}

Guidelines:
- Be specific and factual — only mention technologies you see evidence of.
- For *technologies*, include languages ordered by percentage, then frameworks and notable libraries.
- For *structure*, write 1-2 sentences describing how the project is organised, referencing the concrete directory and file names you see in the tree (e.g. "The project follows a standard Python package layout with source code in `src/`, tests in `tests/`, and configuration in `pyproject.toml`.").
- Do NOT invent information not supported by the provided content.
"""

FILE_SUMMARY_SYSTEM_PROMPT = """\
You are a code analyst. Summarise the following source file in 2-3 sentences: \
what it does, what it exports, and its role in the project.

Return a JSON object with a single key "file_summary" containing your summary.
"""


class SummarizeRepoUseCase:
    """Orchestrates the full repo → summary pipeline."""

    def __init__(
        self,
        repo_fetcher: RepoFetcher,
        llm_gateway: LlmGateway,
        max_context_tokens: int = 12_000,
        max_files_to_fetch: int = 30,
        max_file_size_kb: int = 200,
    ) -> None:
        self._fetcher = repo_fetcher
        self._llm = llm_gateway
        self._max_tokens = max_context_tokens
        self._max_files = max_files_to_fetch
        self._max_size_kb = max_file_size_kb

    async def execute(self, github_url: str) -> SummaryResult:
        """Run the full pipeline and return a structured summary."""
        url = GitHubUrl.from_string(github_url)
        logger.info("Summarising %s", url.full_name)

        # 1. Fetch metadata first (need default_branch), then tree + languages in parallel
        metadata = await self._fetcher.fetch_metadata(url)
        tree, languages = await asyncio.gather(
            self._fetcher.fetch_tree(url, metadata.default_branch),
            self._fetcher.fetch_languages(url),
        )

        if not tree:
            raise EmptyRepositoryError(f"Repository {url.full_name} has no files.")

        # 2. Filter & classify
        classified = filter_and_classify(tree, self._max_size_kb)
        if not classified:
            raise EmptyRepositoryError(
                f"Repository {url.full_name} has no processable files after filtering."
            )

        # 3. Select files to fetch by priority
        files_to_fetch = self._select_files_to_fetch(classified)
        logger.info("Fetching %d files from %s", len(files_to_fetch), url.full_name)

        # 4. Fetch file contents concurrently
        repo_files = await self._fetch_files(url, metadata.default_branch, files_to_fetch)

        # 5. AST skeleton extraction
        skeletons = [
            extract_skeleton(f.path, f.content)
            for f in repo_files
            if f.category in (FileCategory.SOURCE, FileCategory.ENTRY_POINT, FileCategory.TEST)
        ]

        # 6. Graph centrality scoring
        categories_map = {f.path: f.category for f in repo_files}
        sizes_map = {f.path: f.size_bytes for f in repo_files}

        if skeletons:
            scored = score_files(skeletons, categories_map, sizes_map)
        else:
            scored = []

        # 7. Build raw content for each budget slot
        raw_contents = self._build_raw_contents(tree, repo_files, skeletons, scored, languages)

        # 8. Redact secrets
        sanitized, redaction_count = sanitize_batch(raw_contents)
        if redaction_count:
            logger.warning("Redacted %d potential secret(s) from context", redaction_count)

        # 9. Token budgeting
        budgeted = allocate(sanitized, total_budget=self._max_tokens)
        logger.info("Token budget: %d / %d used", budgeted.total_tokens, budgeted.budget_limit)

        # 10. Single-pass or multi-pass summarisation
        if self._needs_multi_pass(budgeted, raw_contents):
            return await self._multi_pass_summarise(
                url, metadata.default_branch, tree, repo_files, scored, budgeted
            )
        return await self._single_pass_summarise(budgeted)

    def _select_files_to_fetch(
        self, classified: list[tuple[FileNode, FileCategory]]
    ) -> list[tuple[FileNode, FileCategory]]:
        priority = {
            FileCategory.README: 0,
            FileCategory.CONFIG: 1,
            FileCategory.ENTRY_POINT: 2,
            FileCategory.SOURCE: 3,
            FileCategory.DOCS: 4,
            FileCategory.TEST: 5,
            FileCategory.OTHER: 6,
        }
        classified.sort(key=lambda item: (priority.get(item[1], 99), item[0].path))
        return classified[: self._max_files]

    async def _fetch_files(
        self,
        url: GitHubUrl,
        branch: str,
        files: list[tuple[FileNode, FileCategory]],
    ) -> list[RepoFile]:
        sem = asyncio.Semaphore(10)

        async def _fetch_one(node: FileNode, category: FileCategory) -> RepoFile | None:
            async with sem:
                try:
                    content = await self._fetcher.fetch_file_content(url, node.path, branch)
                    return RepoFile(
                        path=node.path,
                        content=content,
                        size_bytes=node.size,
                        language=_infer_language(node.path),
                        category=category,
                    )
                except Exception:
                    logger.debug("Failed to fetch %s — skipping", node.path, exc_info=True)
                    return None

        results = await asyncio.gather(
            *(_fetch_one(node, cat) for node, cat in files),
            return_exceptions=False,
        )
        return [r for r in results if r is not None]

    def _build_raw_contents(
        self,
        tree: list[FileNode],
        repo_files: list[RepoFile],
        skeletons: list[FileSkeletonResult],
        scored: list[ScoredFile],
        languages: dict[str, int] | None = None,
    ) -> dict[str, str]:
        contents: dict[str, str] = {}

        if languages:
            total_bytes = sum(languages.values()) or 1
            lang_lines = [
                f"- {lang}: {bytes_count / total_bytes * 100:.1f}%"
                for lang, bytes_count in sorted(languages.items(), key=lambda x: -x[1])
            ]
            contents["languages"] = "\n".join(lang_lines)

        readmes = [f for f in repo_files if f.category == FileCategory.README]
        if readmes:
            contents["readme"] = readmes[0].content

        configs = [f for f in repo_files if f.category == FileCategory.CONFIG]
        if configs:
            parts = []
            for f in configs:
                parts.append(f"### {f.path}\n\n{f.content}")
            contents["config"] = "\n\n".join(parts)

        contents["tree"] = self._render_tree(tree)

        scored_paths = {s.path for s in scored}
        skeleton_map = {sk.path: sk.skeleton_text for sk in skeletons}

        source_parts: list[str] = []
        # Scored files first, in ranked order
        for sf in scored:
            if sf.path in skeleton_map:
                source_parts.append(f"### {sf.path}\n\n{skeleton_map[sf.path]}")

        # Remaining entry points / source files not covered by skeletons
        for f in repo_files:
            if f.path not in scored_paths and f.category in (
                FileCategory.ENTRY_POINT,
                FileCategory.SOURCE,
            ):
                source_parts.append(f"### {f.path}\n\n{f.content[:2000]}")

        if source_parts:
            contents["source"] = "\n\n".join(source_parts)

        return contents

    @staticmethod
    def _render_tree(tree: list[FileNode]) -> str:
        lines: list[str] = []
        for node in tree:
            if node.type == "tree":
                lines.append(f"{node.path}/")
            else:
                lines.append(node.path)
        # Cap at 200 lines
        if len(lines) > 200:
            lines = lines[:200]
            lines.append(f"… and {len(tree) - 200} more files")
        return "\n".join(lines)

    def _needs_multi_pass(
        self, budgeted: BudgetedContent, raw: dict[str, str]
    ) -> bool:
        """Return True when raw source content significantly exceeds its slot budget."""
        source_slot = budgeted.get_slot("source")
        raw_source = raw.get("source", "")
        if not raw_source or not source_slot:
            return False
        raw_tokens = count_tokens(raw_source)
        return raw_tokens > source_slot.max_tokens * 2

    async def _single_pass_summarise(self, budgeted: BudgetedContent) -> SummaryResult:
        context = assemble(budgeted)
        return await self._call_llm_for_summary(context)

    async def _multi_pass_summarise(
        self,
        url: GitHubUrl,
        branch: str,
        tree: list[FileNode],
        repo_files: list[RepoFile],
        scored: list[ScoredFile],
        budgeted: BudgetedContent,
    ) -> SummaryResult:
        logger.info("Using multi-pass summarisation for %s", url.full_name)

        source_files = [f for f in repo_files if f.category in (
            FileCategory.SOURCE, FileCategory.ENTRY_POINT
        )]

        # Summarise top 8 scored source files individually
        scored_paths = [s.path for s in scored[:8]]
        top_sources = [f for f in source_files if f.path in scored_paths]

        file_summaries: list[str] = []
        for f in top_sources:
            try:
                raw_summary = await self._llm.complete(
                    FILE_SUMMARY_SYSTEM_PROMPT,
                    f"File: {f.path}\n\n{f.content[:3000]}",
                )
                try:
                    summary_data = json.loads(raw_summary)
                    summary_text = summary_data.get("file_summary", raw_summary)
                except json.JSONDecodeError:
                    summary_text = raw_summary.strip()
                file_summaries.append(f"**{f.path}**: {summary_text}")
            except Exception:
                logger.debug("Multi-pass: failed to summarise %s", f.path, exc_info=True)

        # Re-budget with file summaries replacing raw source
        file_summary_text = "\n\n".join(file_summaries) if file_summaries else ""
        readme_slot = budgeted.get_slot("readme")
        config_slot = budgeted.get_slot("config")
        tree_slot = budgeted.get_slot("tree")

        pass2_contents = {
            "readme": readme_slot.content if readme_slot else "",
            "config": config_slot.content if config_slot else "",
            "tree": tree_slot.content if tree_slot else "",
            "source": file_summary_text,
        }
        pass2_budget = allocate(pass2_contents, total_budget=self._max_tokens)
        context = assemble(pass2_budget)

        return await self._call_llm_for_summary(context)

    async def _call_llm_for_summary(self, context: str) -> SummaryResult:
        raw = await self._llm.complete(SYSTEM_PROMPT, context)
        return self._parse_llm_response(raw)

    @staticmethod
    def _parse_llm_response(raw: str) -> SummaryResult:
        text = raw.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            first_nl = text.index("\n") if "\n" in text else 3
            text = text[first_nl + 1 :]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LlmError(f"LLM returned invalid JSON: {exc}") from exc

        summary = data.get("summary")
        technologies = data.get("technologies")
        structure = data.get("structure")

        if not isinstance(summary, str) or not summary:
            raise LlmError("LLM response missing 'summary' field.")
        if not isinstance(technologies, list):
            technologies = []
        if not isinstance(structure, str):
            structure = ""

        technologies = [str(t) for t in technologies if t]

        return SummaryResult(
            summary=summary,
            technologies=technologies,
            structure=structure,
        )


_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C",
    ".hpp": "C++",
    ".swift": "Swift",
    ".php": "PHP",
    ".sh": "Shell",
    ".bash": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".md": "Markdown",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
}


def _infer_language(path: str) -> str:
    dot = path.rfind(".")
    if dot == -1:
        return "unknown"
    return _LANGUAGE_MAP.get(path[dot:].lower(), "unknown")
