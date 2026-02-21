"""Port: LLM gateway — defined by the domain, implemented by infrastructure."""

from __future__ import annotations

from typing import Protocol


class LlmGateway(Protocol):
    """Abstract contract for interacting with a large-language model."""

    async def complete(
        self, system_prompt: str, user_prompt: str, *, json_mode: bool = True
    ) -> str:
        """Send a system + user prompt pair and return the raw completion text."""
        ...
