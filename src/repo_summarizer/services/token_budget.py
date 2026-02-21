"""Deterministic token-budget allocator.

Uses ``tiktoken`` for exact token counting and allocates a fixed budget
across content categories with a rollover mechanism so unused capacity
is never wasted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import tiktoken

# ── Constants ───────────────────────────────────────────────────────────────

_ENCODING_NAME = "cl100k_base"  # GPT-4o family

# Budget proportions (must sum to ≤ 1.0 — remainder is the safety reserve)
_SLOT_PROPORTIONS: list[tuple[str, float]] = [
    ("languages", 0.02),
    ("readme", 0.28),
    ("config", 0.15),
    ("tree", 0.10),
    ("source", 0.40),
    # Implicit 5 % reserve
]


# ── Public helpers ──────────────────────────────────────────────────────────

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        _encoder = tiktoken.get_encoding(_ENCODING_NAME)
    return _encoder


def count_tokens(text: str) -> int:
    """Return the exact token count for *text* under cl100k_base."""
    return len(_get_encoder().encode(text))


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate *text* to fit within *max_tokens*, cutting at line boundaries.

    Attempts to preserve complete lines rather than splitting mid-word.
    """
    tokens = _get_encoder().encode(text)
    if len(tokens) <= max_tokens:
        return text

    # Decode the truncated tokens
    truncated = _get_encoder().decode(tokens[:max_tokens])

    # Roll back to the last newline for a clean cut
    last_nl = truncated.rfind("\n")
    if last_nl > len(truncated) // 2:
        truncated = truncated[: last_nl + 1]

    return truncated + "\n[… truncated to fit token budget]"


# ── Budget allocation ───────────────────────────────────────────────────────


@dataclass
class BudgetSlot:
    """One slot within the token budget."""

    name: str
    max_tokens: int
    content: str = ""
    used_tokens: int = 0


@dataclass
class BudgetedContent:
    """The final budgeted artefact ready for prompt assembly."""

    slots: list[BudgetSlot] = field(default_factory=list)
    total_tokens: int = 0
    budget_limit: int = 0

    def get_slot(self, name: str) -> BudgetSlot | None:
        for slot in self.slots:
            if slot.name == name:
                return slot
        return None


def allocate(
    contents: dict[str, str],
    total_budget: int = 12_000,
) -> BudgetedContent:
    """Allocate *contents* (keyed by slot name) within *total_budget* tokens.

    Unused tokens from earlier slots roll over to subsequent slots.

    Parameters
    ----------
    contents:
        Mapping of ``{"readme": "...", "config": "...", "tree": "...",
        "source": "..."}`` with the raw text for each category.
    total_budget:
        Maximum tokens to allocate (excluding system prompt).
    """
    reserve = int(total_budget * 0.05)
    usable = total_budget - reserve

    slots: list[BudgetSlot] = []
    remaining = usable

    for slot_name, proportion in _SLOT_PROPORTIONS:
        raw_text = contents.get(slot_name, "")
        slot_max = int(usable * proportion)

        # Allow rollover: slot can use up to its share + unspent remainder
        effective_max = min(slot_max + (remaining - slot_max), remaining)
        effective_max = max(effective_max, 0)

        if not raw_text:
            slots.append(BudgetSlot(name=slot_name, max_tokens=effective_max))
            # All of this slot's capacity rolls into remaining (already did nothing)
            continue

        actual_tokens = count_tokens(raw_text)

        if actual_tokens <= effective_max:
            fitted_text = raw_text
            used = actual_tokens
        else:
            fitted_text = truncate_to_budget(raw_text, effective_max)
            used = count_tokens(fitted_text)

        remaining -= used
        slots.append(
            BudgetSlot(
                name=slot_name,
                max_tokens=effective_max,
                content=fitted_text,
                used_tokens=used,
            )
        )

    total_used = sum(s.used_tokens for s in slots)
    return BudgetedContent(slots=slots, total_tokens=total_used, budget_limit=total_budget)
