"""The language-model port. Application code depends on this, never on a vendor SDK."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    # What the provider reports, for logs and later cost tracking. None when not reported.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMError(Exception):
    """The request cannot succeed as sent (bad key, unknown model, empty answer, ...).

    The message is safe to log but is never sent to API clients.
    """


class LLMUnavailableError(LLMError):
    """A temporary failure (rate limit, timeout, 5xx). Trying again later may work."""


class LLMProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    async def complete(self, messages: Sequence[ChatMessage]) -> LLMResult: ...
