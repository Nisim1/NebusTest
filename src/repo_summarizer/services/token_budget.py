"""Deterministic token-budget allocator with rollover across slots."""

from __future__ import annotations

from dataclasses import dataclass, field

import tiktoken

_ENCODING_NAME = "cl100k_base"  # GPT-4o family

# Proportions must sum to ≤ 1.0; remaining 5% is the safety reserve
_SLOT_PROPORTIONS: list[tuple[str, float]] = [
    ("languages", 0.02),
    ("readme", 0.28),
    ("config", 0.15),
    ("tree", 0.10),
    ("source", 0.40),
]

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        _encoder = tiktoken.get_encoding(_ENCODING_NAME)
    return _encoder


def count_tokens(text: str) -> int:
    """Return the exact token count for text under cl100k_base."""
    return len(_get_encoder().encode(text))


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate text to fit within max_tokens, cutting at line boundaries."""
    tokens = _get_encoder().encode(text)
    if len(tokens) <= max_tokens:
        return text

    truncated = _get_encoder().decode(tokens[:max_tokens])

    # Roll back to last newline for a clean cut
    last_nl = truncated.rfind("\n")
    if last_nl > len(truncated) // 2:
        truncated = truncated[: last_nl + 1]

    return truncated + "\n[… truncated to fit token budget]"


@dataclass
class BudgetSlot:
    name: str
    max_tokens: int
    content: str = ""
    used_tokens: int = 0


@dataclass
class BudgetedContent:
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
    """Allocate contents within total_budget tokens; unused tokens roll over."""
    reserve = int(total_budget * 0.05)
    usable = total_budget - reserve

    slots: list[BudgetSlot] = []
    remaining = usable

    for slot_name, proportion in _SLOT_PROPORTIONS:
        raw_text = contents.get(slot_name, "")
        slot_max = int(usable * proportion)

        # Allow rollover: slot can consume up to its share + unspent remainder
        effective_max = min(slot_max + (remaining - slot_max), remaining)
        effective_max = max(effective_max, 0)

        if not raw_text:
            slots.append(BudgetSlot(name=slot_name, max_tokens=effective_max))
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
