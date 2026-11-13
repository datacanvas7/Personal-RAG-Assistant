"""Startup check that the configured embedding model matches what the database holds.

Vectors from different models are not comparable: searching a 384-d BGE index with an
OpenAI query vector returns plausible-looking garbage rather than an error. This check
turns the three ways that can happen into a refusal to start, with instructions:

* the database column has a different dimension than the configuration says;
* ready documents were embedded by a different model than the one now configured;
* (warning only) ready documents have no vectors yet, because they predate embeddings.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_REINDEX_HINT = "Run `python -m app.scripts.reindex` to re-embed the existing documents."


class EmbeddingConfigurationError(RuntimeError):
    """The configured embedding model cannot be used with the existing index."""


@dataclass(frozen=True)
class IndexState:
    column_dimension: int | None
    # How many *ready* documents each embedding model indexed (None = no vectors yet).
    ready_documents_by_model: dict[str | None, int]


def read_index_state(connection: Connection) -> IndexState:
    # For pgvector the type modifier of vector(N) is N itself.
    column_dimension = connection.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
        )
    ).scalar_one_or_none()
    rows = connection.execute(
        text(
            "SELECT embedding_model, count(*) AS n FROM documents "
            "WHERE status = 'ready' GROUP BY embedding_model"
        )
    ).all()
    return IndexState(
        column_dimension=column_dimension if column_dimension and column_dimension > 0 else None,
        ready_documents_by_model={row.embedding_model: row.n for row in rows},
    )


def evaluate(state: IndexState, provider: EmbeddingProvider) -> list[str]:
    """Raise ``EmbeddingConfigurationError`` if the index is unusable; return warnings."""
    if state.column_dimension is not None and state.column_dimension != provider.dimension:
        raise EmbeddingConfigurationError(
            f"EMBEDDING_DIMENSION is {provider.dimension} but the database column is "
            f"vector({state.column_dimension}). Changing the dimension needs a database "
            f"migration and a re-index; otherwise set EMBEDDING_DIMENSION back."
        )

    foreign = {
        model: count
        for model, count in state.ready_documents_by_model.items()
        if model is not None and model != provider.model_id
    }
    if foreign:
        found = ", ".join(
            f"{model} ({count} documents)" for model, count in sorted(foreign.items())
        )
        raise EmbeddingConfigurationError(
            f"The index was built with {found}, but the configured model is "
            f"{provider.model_id}. Mixing models gives meaningless search results. "
            f"Switch the configuration back, or {_REINDEX_HINT}"
        )

    warnings: list[str] = []
    unembedded = state.ready_documents_by_model.get(None, 0)
    if unembedded:
        warnings.append(
            f"{unembedded} ready document(s) have no embeddings and will not appear in "
            f"search results. {_REINDEX_HINT}"
        )
    return warnings


def check_embedding_index(engine: Engine, provider: EmbeddingProvider) -> list[str]:
    with engine.connect() as connection:
        state = read_index_state(connection)
    warnings = evaluate(state, provider)
    for warning in warnings:
        logger.warning(warning)
    return warnings
