"""Check the language-model configuration against the real service.

    python -m app.scripts.check_llm            # list the models the key can use, then ask one
                                               # trivial question with the configured model

Model names change (Gemini retires models regularly); this tells you what is available now.
The API key is never printed.
"""

import asyncio
import sys

import openai

from app.core.config import get_settings
from app.llm.base import ChatMessage, LLMError
from app.llm.factory import build_llm_provider


async def _main() -> int:
    settings = get_settings()
    print(f"endpoint: {settings.llm_base_url}")  # noqa: T201
    print(f"model:    {settings.llm_model}")  # noqa: T201
    provider = build_llm_provider(settings)
    if provider is None:
        print("LLM_API_KEY is not set.")  # noqa: T201
        return 1

    assert settings.llm_api_key is not None  # noqa: S101
    client = openai.AsyncOpenAI(
        base_url=settings.llm_base_url, api_key=settings.llm_api_key.get_secret_value()
    )
    try:
        listing = [model.id.removeprefix("models/") async for model in client.models.list()]
        names = sorted(listing)
    except openai.OpenAIError as error:
        print(f"listing models failed: {type(error).__name__}")  # noqa: T201
        names = []
    if names:
        print(f"{len(names)} models available, e.g.:")  # noqa: T201
        for name in names:
            if "flash" in name or "hydrogen" in name:
                print(f"  {name}")  # noqa: T201
        if settings.llm_model not in names:
            print(f"WARNING: {settings.llm_model} is not in the list; set LLM_MODEL.")  # noqa: T201

    try:
        result = await provider.complete([ChatMessage("user", "Reply with the single word: ready")])
    except LLMError as error:
        print(f"test request failed: {error}")  # noqa: T201
        return 1
    print(f"test request ok: {result.text!r} ({result.completion_tokens} output tokens)")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
