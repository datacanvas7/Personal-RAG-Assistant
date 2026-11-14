"""The OpenAI-compatible adapter, with the SDK client faked."""

from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from app.core.config import Settings
from app.llm.base import ChatMessage, LLMError, LLMUnavailableError
from app.llm.factory import build_llm_provider
from app.llm.openai_compatible import OpenAICompatibleProvider

MESSAGES = [ChatMessage("system", "rules"), ChatMessage("user", "hello")]


class FakeClient:
    def __init__(self, *, content: str | None = "Hi [1]", finish: str = "stop") -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.content = content
        self.finish = finish
        self.choices_empty = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        choices = (
            []
            if self.choices_empty
            else [
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content), finish_reason=self.finish
                )
            ]
        )
        return SimpleNamespace(
            choices=choices, usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3)
        )


def _provider(client: FakeClient, **overrides: Any) -> OpenAICompatibleProvider:
    options: dict[str, Any] = {
        "base_url": "https://llm.example/v1/",
        "api_key": "key",
        "model": "m1",
        "temperature": 0.2,
        "max_output_tokens": 500,
        "timeout_seconds": 5,
        "client": client,
    }
    options.update(overrides)
    return OpenAICompatibleProvider(**options)


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://llm.example/v1/chat/completions")
    return cls(
        "secret provider message", response=httpx2.Response(status, request=request), body=None
    )


async def test_sends_messages_and_settings_and_returns_text_with_usage() -> None:
    client = FakeClient(content="  Every ninety days [1].  ")

    result = await _provider(client).complete(MESSAGES)

    assert result.text == "Every ninety days [1]."
    assert (result.prompt_tokens, result.completion_tokens) == (11, 3)
    call = client.calls[0]
    assert call["model"] == "m1"
    assert call["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
    ]
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 500
    assert "reasoning_effort" not in call


async def test_reasoning_effort_is_sent_only_when_configured() -> None:
    client = FakeClient()

    await _provider(client, reasoning_effort="low").complete(MESSAGES)

    assert client.calls[0]["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=httpx2.Request("POST", "https://llm.example")),
        openai.APITimeoutError(request=httpx2.Request("POST", "https://llm.example")),
        _status_error(openai.RateLimitError, 429),
        _status_error(openai.InternalServerError, 503),
    ],
    ids=["connection", "timeout", "rate-limit", "server-error"],
)
async def test_temporary_failures_are_marked_retryable(error: Exception) -> None:
    client = FakeClient()
    client.error = error

    with pytest.raises(LLMUnavailableError):
        await _provider(client).complete(MESSAGES)


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (openai.AuthenticationError, 401),
        (openai.PermissionDeniedError, 403),
        (openai.NotFoundError, 404),
        (openai.BadRequestError, 400),
    ],
)
async def test_rejected_requests_are_permanent_and_do_not_leak_provider_text(
    cls: type[openai.APIStatusError], status: int
) -> None:
    client = FakeClient()
    client.error = _status_error(cls, status)

    with pytest.raises(LLMError) as raised:
        await _provider(client).complete(MESSAGES)

    assert not isinstance(raised.value, LLMUnavailableError)
    assert "secret provider message" not in str(raised.value)
    assert str(status) in str(raised.value)


async def test_an_empty_answer_is_an_error_not_a_blank_reply() -> None:
    client = FakeClient(content=None, finish="length")

    with pytest.raises(LLMError, match="empty answer.*length"):
        await _provider(client).complete(MESSAGES)


async def test_no_choices_is_an_error() -> None:
    client = FakeClient()
    client.choices_empty = True

    with pytest.raises(LLMError, match="no choices"):
        await _provider(client).complete(MESSAGES)


def test_factory_returns_nothing_without_a_key_so_the_rest_of_the_api_still_works() -> None:
    assert build_llm_provider(Settings(postgres_password="x")) is None
    assert build_llm_provider(Settings(postgres_password="x", llm_api_key="")) is None


def test_factory_builds_a_provider_from_settings() -> None:
    settings = Settings(
        postgres_password="x", llm_api_key="k", llm_model="gemini-test", llm_reasoning_effort=""
    )

    provider = build_llm_provider(settings)

    assert provider is not None
    assert provider.model_id == "gemini-test"
    assert settings.llm_base_url.startswith("https://generativelanguage.googleapis.com/")
