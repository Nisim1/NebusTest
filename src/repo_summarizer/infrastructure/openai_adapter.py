"""OpenAI adapter — implements the LlmGateway port."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI, AuthenticationError, RateLimitError

from repo_summarizer.domain.exceptions import LlmError

logger = logging.getLogger(__name__)


class OpenAIAdapter:
    """Concrete ``LlmGateway`` backed by the OpenAI chat-completions API."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=5)
        self._model = model

    async def complete(
        self, system_prompt: str, user_prompt: str, *, json_mode: bool = True
    ) -> str:
        """Send a system + user prompt and return the completion text."""
        try:
            kwargs: dict[str, object] = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await self._client.chat.completions.create(**kwargs)  # type: ignore[arg-type]

            choice = response.choices[0]
            content = choice.message.content

            if not content:
                raise LlmError("LLM returned an empty response.")

            return content

        except AuthenticationError as exc:
            raise LlmError(
                "Invalid OpenAI API key. "
                "Set a valid key in the OPENAI_API_KEY environment variable."
            ) from exc

        except RateLimitError as exc:
            detail = str(exc)
            logger.error("OpenAI RateLimitError: %s", detail)
            raise LlmError(
                f"OpenAI rate limit / quota error: {detail}"
            ) from exc

        except LlmError:
            raise

        except Exception as exc:
            raise LlmError(f"LLM call failed: {exc}") from exc

    async def close(self) -> None:
        """Release underlying HTTP resources."""
        await self._client.close()
