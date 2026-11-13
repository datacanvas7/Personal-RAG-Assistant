"""Hosted embeddings from the OpenAI API.

Document text leaves the machine, so this is opt-in (``EMBEDDING_PROVIDER=openai``).
``text-embedding-3-*`` models can return shorter vectors, which is how a 1536-d model fills
the same 384-column as the local default.
"""

import logging
from collections.abc import Sequence
from typing import Any

import openai

from app.embeddings.base import EmbeddingError, EmbeddingUnavailableError

logger = logging.getLogger(__name__)

# Models that accept the ``dimensions`` parameter (others only return their native size).
_SHORTENABLE_PREFIX = "text-embedding-3"


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimension: int,
        batch_size: int = 100,
        timeout_seconds: float = 30.0,
        client: Any = None,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._batch_size = batch_size
        # The SDK retries connection errors, 429s and 5xx twice by default; whatever still
        # fails is surfaced as EmbeddingUnavailableError for the task-level retry.
        self._client = client or openai.OpenAI(api_key=api_key, timeout=timeout_seconds)

    @property
    def model_id(self) -> str:
        return f"openai:{self._model}:{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(self._embed(list(texts[start : start + self._batch_size])))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        options: dict[str, Any] = {}
        if self._model.startswith(_SHORTENABLE_PREFIX):
            options["dimensions"] = self._dimension
        try:
            response = self._client.embeddings.create(
                model=self._model, input=texts, encoding_format="float", **options
            )
        except (
            openai.APIConnectionError,  # includes timeouts
            openai.RateLimitError,
            openai.InternalServerError,
        ) as error:
            raise EmbeddingUnavailableError(
                f"OpenAI embeddings temporarily unavailable ({type(error).__name__})"
            ) from error
        except openai.APIStatusError as error:
            # 400/401/403/404: a bad key, model name or request. Retrying will not help.
            raise EmbeddingError(
                f"OpenAI rejected the request (HTTP {error.status_code})"
            ) from error

        items = sorted(response.data, key=lambda item: item.index)
        vectors: list[list[float]] = [list(item.embedding) for item in items]
        if len(vectors) != len(texts) or any(len(v) != self._dimension for v in vectors):
            raise EmbeddingError(
                f"OpenAI returned vectors that do not match EMBEDDING_DIMENSION={self._dimension}"
            )
        return vectors
