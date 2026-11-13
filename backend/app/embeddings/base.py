"""The embedding contract the rest of the application depends on.

Nothing outside ``app/embeddings`` imports a model library. Ingestion and search receive an
``EmbeddingProvider`` and cannot tell whether vectors come from a local model or a hosted
API, which is what makes the backend replaceable.
"""

from collections.abc import Sequence
from typing import Protocol


class EmbeddingError(Exception):
    """Embedding failed for a reason a retry cannot fix (bad key, wrong dimension, ...).

    The message is for logs and operators; it is never shown to end users.
    """


class EmbeddingUnavailableError(EmbeddingError):
    """Embedding failed for a reason that may pass: timeout, rate limit, model still
    downloading, provider outage. Callers retry these."""


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str:
        """Identifies the model *and* the vector size, e.g. ``openai:text-embedding-3-small:384``.

        Stored with every indexed document. Vectors with different ids are never compared.
        """
        ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in order. Blocking: call it from a worker or a thread."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query. May differ from ``embed_documents`` (BGE prefixes queries)."""
        ...
