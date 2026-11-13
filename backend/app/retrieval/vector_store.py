"""Similarity search over stored chunk vectors (PostgreSQL + pgvector).

We write this SQL ourselves, rather than using a framework's vector store, so the ownership
filter is visible in the query: every search carries ``WHERE document_chunks.user_id = :uid``
and nothing in the call chain can omit it, because ``user_id`` is a required argument.

Writing vectors is deliberately *not* here: chunks and vectors are inserted by the ingestion
transaction (``SqlIngestionStore.replace_chunks``) so a document is never half-indexed.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    content: str
    score: float  # cosine similarity: 1.0 identical direction, 0.0 unrelated, -1.0 opposite


class VectorStore(Protocol):
    async def search(
        self,
        user_id: uuid.UUID,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[ScoredChunk]: ...


class PgVectorStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        user_id: uuid.UUID,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[ScoredChunk]:
        # HNSW is an approximate index, and a WHERE clause is applied to the candidates it
        # returns (default 40). For a user who owns a small share of all chunks most
        # candidates belong to someone else, so a plain query can return fewer than top_k
        # rows even though more exist. Iterative scan (pgvector 0.8) makes the index keep
        # scanning until enough rows pass the filter. SET LOCAL lasts for this transaction.
        await self._session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))

        distance = DocumentChunk.embedding.cosine_distance(list(query_embedding))
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.page_number,
                DocumentChunk.content,
                distance.label("distance"),
            )
            .where(
                DocumentChunk.user_id == user_id,
                DocumentChunk.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(top_k)
        )
        if document_ids is not None:
            # Combined with the user filter above, so ids of other users' documents (or
            # ids that do not exist) simply match nothing.
            statement = statement.where(DocumentChunk.document_id.in_(document_ids))

        rows = (await self._session.execute(statement)).all()
        # relaxed_order may return rows slightly out of order; sort them properly.
        hits = [
            ScoredChunk(
                chunk_id=row.id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                content=row.content,
                score=1.0 - float(row.distance),
            )
            for row in rows
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits
