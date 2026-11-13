"""Re-embed documents whose vectors are missing or were made by another model.

    python -m app.scripts.reindex            # in Docker: docker compose run --rm backend ...

Switching the embedding model is a deliberate operation: set the new EMBEDDING_* values,
run this, and let the worker finish. In one transaction it

1. finds ready documents whose ``embedding_model`` is not the configured model,
2. erases their vectors (so they cannot be searched against vectors from another model),
3. marks them ``pending``,

and then queues each for ingestion, which replaces their chunks and vectors atomically.
A document that was queued twice is harmless: ingestion is idempotent.
"""

import logging
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sync_engine
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.services.queue import enqueue_ingestion_sync

logger = logging.getLogger(__name__)


def mark_stale_documents(engine: Engine, provider: EmbeddingProvider) -> list[uuid.UUID]:
    """Return the ids of the documents that were reset and need to be queued."""
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "UPDATE documents SET status = 'pending', error_message = NULL "
                "WHERE status = 'ready' AND embedding_model IS DISTINCT FROM :model "
                "RETURNING id"
            ),
            {"model": provider.model_id},
        ).all()
        ids = [row.id for row in rows]
        if ids:
            connection.execute(
                text("UPDATE document_chunks SET embedding = NULL WHERE document_id = ANY(:ids)"),
                {"ids": ids},
            )
    return ids


def main() -> int:
    configure_logging(get_settings().log_level)
    provider = get_embedding_provider()
    ids = mark_stale_documents(get_sync_engine(), provider)
    for document_id in ids:
        enqueue_ingestion_sync(document_id)
    logger.info("queued %d document(s) for re-embedding with %s", len(ids), provider.model_id)
    print(f"Queued {len(ids)} document(s) for re-embedding with {provider.model_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
