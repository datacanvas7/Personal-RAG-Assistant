"""Builds the configured language model. The only place that knows the implementation."""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider


def build_llm_provider(settings: Settings) -> LLMProvider | None:
    """None when no key is configured: the rest of the API still works, only answering
    is unavailable. A local server (Ollama) ignores the key, so any placeholder will do."""
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
        return None
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        reasoning_effort=settings.llm_reasoning_effort or None,
    )


@lru_cache
def get_llm_provider() -> LLMProvider | None:
    return build_llm_provider(get_settings())
