"""Search use case: embed the query, find the nearest chunks, attach document names."""

import asyncio
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.core.errors import ServiceUnavailableError
from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.retrieval.vector_store import VectorStore
from app.schemas.search import SearchHit

logger = logging.getLogger(__name__)


class DocumentNames(Protocol):
    async def filenames(
        self, user_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, str]: ...


class SearchService:
    def __init__(
        self, *, embedder: EmbeddingProvider, vectors: VectorStore, documents: DocumentNames
    ) -> None:
        self._embedder = embedder
        self._vectors = vectors
        self._documents = documents

    async def search(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        top_k: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[SearchHit]:
        # The embedder is synchronous (CPU-bound model or blocking HTTP client): run it in a
        # thread so the event loop keeps serving other requests.
        try:
            query_vector = await asyncio.to_thread(self._embedder.embed_query, query)
        except EmbeddingError:
            # Details (which provider, what failed) go to the log, not to the client.
            logger.exception("embedding the search query failed")
            raise ServiceUnavailableError("Search is temporarily unavailable.") from None

        chunks = await self._vectors.search(
            user_id, query_vector, top_k=top_k, document_ids=document_ids
        )
        if not chunks:
            return []

        names = await self._documents.filenames(user_id, list({c.document_id for c in chunks}))
        return [
            SearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=names[chunk.document_id],
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=chunk.score,
            )
            for chunk in chunks
            if chunk.document_id in names  # a document deleted since the vector query
        ]
