"""Builds the configured embedding provider. The only place that knows the implementations."""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.sentence_transformers import SentenceTransformerProvider


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        # Settings validation guarantees the key is present.
        assert settings.openai_api_key is not None  # noqa: S101
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.resolved_embedding_model,
            dimension=settings.embedding_dimension,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    return SentenceTransformerProvider(
        model_name=settings.resolved_embedding_model,
        dimension=settings.embedding_dimension,
        query_prefix=settings.embedding_query_prefix,
        batch_size=settings.embedding_batch_size,
    )


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """One provider per process: the local model is loaded once and then reused."""
    return build_embedding_provider(get_settings())
