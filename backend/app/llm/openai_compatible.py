"""Chat completions over the OpenAI wire protocol.

Gemini (``https://generativelanguage.googleapis.com/v1beta/openai/``), OpenAI, Groq,
OpenRouter and Ollama (``http://host:11434/v1``) all speak it, so one adapter covers them and
switching is a change of ``LLM_BASE_URL`` / ``LLM_MODEL`` / ``LLM_API_KEY``, not of code.
"""

import logging
from collections.abc import Sequence
from typing import Any

import openai

from app.llm.base import ChatMessage, LLMError, LLMResult, LLMUnavailableError

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        reasoning_effort: str | None = None,
        client: Any = None,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        # One quick retry for connection errors and 5xx. Free tiers answer 429 for minutes,
        # so retrying a rate limit inside the request only makes the user wait.
        self._client = client or openai.AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_seconds, max_retries=1
        )

    @property
    def model_id(self) -> str:
        return self._model

    async def complete(self, messages: Sequence[ChatMessage]) -> LLMResult:
        options: dict[str, Any] = {}
        payload: list[Any] = [{"role": m.role, "content": m.content} for m in messages]
        if self._reasoning_effort:
            options["reasoning_effort"] = self._reasoning_effort
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=payload,
                temperature=self._temperature,
                max_tokens=self._max_output_tokens,
                **options,
            )
        except (
            openai.APIConnectionError,  # includes timeouts
            openai.RateLimitError,
            openai.InternalServerError,
        ) as error:
            raise LLMUnavailableError(
                f"language model temporarily unavailable ({type(error).__name__})"
            ) from error
        except openai.APIStatusError as error:
            # 400/401/403/404: a bad key, an unknown model, a rejected request.
            raise LLMError(
                f"language model rejected the request (HTTP {error.status_code})"
            ) from error

        if not response.choices:
            raise LLMError("language model returned no choices")
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            # Reasoning models can spend the whole token budget on thinking and return
            # nothing; surface it instead of presenting an empty answer.
            raise LLMError(
                f"language model returned an empty answer (finish={choice.finish_reason})"
            )
        usage = response.usage
        return LLMResult(
            text=text,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
