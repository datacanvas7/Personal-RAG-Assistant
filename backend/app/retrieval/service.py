"""Search use case: embed the query, retrieve candidates, rerank, attach document names.

Three retrieval modes share one pipeline:

* ``vector``  - nearest chunks by embedding similarity (the Phase 5 behaviour);
* ``keyword`` - chunks containing the query's words (PostgreSQL full-text search);
* ``hybrid``  - both, merged with Reciprocal Rank Fusion.

Whatever the mode, an optional reranker then reorders a wider candidate pool, and the best
``top_k`` are returned. ``score`` on every hit is the cosine similarity to the query.
"""

import asyncio
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from app.core.errors import ServiceUnavailableError
from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.retrieval.fusion import fuse_rrf
from app.retrieval.keyword_store import KeywordStore
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import ScoredChunk, VectorStore
from app.schemas.search import SearchHit

logger = logging.getLogger(__name__)

RetrievalMode = Literal["vector", "keyword", "hybrid"]
MAX_CANDIDATES = 200


class DocumentNames(Protocol):
    async def filenames(
        self, user_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, str]: ...


class SearchService:
    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        vectors: VectorStore,
        documents: DocumentNames,
        keywords: KeywordStore | None = None,
        reranker: Reranker | None = None,
        mode: RetrievalMode = "vector",
        candidate_multiplier: int = 4,
    ) -> None:
        if mode != "vector" and keywords is None:
            raise ValueError(f"retrieval mode {mode!r} needs a keyword store")
        self._embedder = embedder
        self._vectors = vectors
        self._documents = documents
        self._keywords = keywords
        self._reranker = reranker
        self._mode = mode
        self._multiplier = candidate_multiplier

    async def search(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        top_k: int,
        document_ids: Sequence[uuid.UUID] | None = None,
        content_types: Sequence[str] | None = None,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> list[SearchHit]:
        # The embedder is synchronous (CPU-bound model or blocking HTTP client): run it in a
        # thread so the event loop keeps serving other requests.
        try:
            query_vector = await asyncio.to_thread(self._embedder.embed_query, query)
        except EmbeddingError:
            # Details (which provider, what failed) go to the log, not to the client.
            logger.exception("embedding the search query failed")
            raise ServiceUnavailableError("Search is temporarily unavailable.") from None

        # Fusion and reranking need more candidates than the caller asked for: the answer to
        # "which five are best?" can sit at position eight of either list.
        wide = self._mode == "hybrid" or self._reranker is not None
        pool = min(top_k * self._multiplier, MAX_CANDIDATES) if wide else top_k
        ranked: list[list[ScoredChunk]] = []
        if self._mode in ("vector", "hybrid"):
            ranked.append(
                await self._vectors.search(
                    user_id,
                    query_vector,
                    top_k=pool,
                    document_ids=document_ids,
                    content_types=content_types,
                    page_from=page_from,
                    page_to=page_to,
                )
            )
        if self._mode in ("keyword", "hybrid"):
            if self._keywords is None:  # pragma: no cover - rejected in __init__
                raise ValueError("keyword search is not configured")
            ranked.append(
                await self._keywords.search(
                    user_id,
                    query,
                    query_vector,
                    limit=pool,
                    document_ids=document_ids,
                    content_types=content_types,
                    page_from=page_from,
                    page_to=page_to,
                )
            )
        chunks = ranked[0] if len(ranked) == 1 else fuse_rrf(ranked)
        if self._reranker is not None:
            chunks = self._reranker.rerank(query, chunks)
        chunks = chunks[:top_k]
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
