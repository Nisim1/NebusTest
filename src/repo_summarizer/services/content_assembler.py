"""Content assembler — builds the structured LLM context from budgeted slots.

This is the final transformation before text enters the prompt template.
"""

from __future__ import annotations

from repo_summarizer.services.token_budget import BudgetedContent


def assemble(budget: BudgetedContent) -> str:
    """Combine all non-empty budget slots into a single structured context block."""
    sections: list[str] = []

    _HEADERS = {
        "languages": "## Repository Languages (from GitHub)",
        "readme": "## README",
        "config": "## Configuration / Metadata Files",
        "tree": "## Directory Structure",
        "source": "## Key Source Files (AST Skeletons)",
    }

    for slot in budget.slots:
        if not slot.content:
            continue
        header = _HEADERS.get(slot.name, f"## {slot.name.title()}")
        sections.append(f"{header}\n\n{slot.content}")

    return "\n\n---\n\n".join(sections)
