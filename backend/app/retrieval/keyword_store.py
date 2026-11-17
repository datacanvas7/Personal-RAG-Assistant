"""Keyword (full-text) search over chunks: the lexical half of hybrid retrieval.

Embeddings capture meaning but blur exact strings: a product code, a surname or a rare term
may score no higher than a vaguely related paragraph. PostgreSQL full-text search is the
opposite: it matches the words themselves (after English stemming) and ignores meaning.
Combining the two (see ``fusion.py``) is what "hybrid search" means.

The ownership filter is applied through ``restrict_chunks`` exactly as in the vector store.
"""

import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk
from app.retrieval.filters import restrict_chunks
from app.retrieval.vector_store import ScoredChunk


class KeywordStore(Protocol):
    async def search(
        self,
        user_id: uuid.UUID,
        query: str,
        query_embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
        content_types: Sequence[str] | None = None,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> list[ScoredChunk]:
        """Chunks containing the query's words, best lexical match first.

        ``score`` of each result is still the *cosine similarity* to ``query_embedding``,
        so one number means one thing wherever a chunk came from (the relevance threshold
        and the API both rely on that). The lexical rank only decides the order.
        """
        ...


class PgKeywordStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        user_id: uuid.UUID,
        query: str,
        query_embedding: Sequence[float],
        *,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
        content_types: Sequence[str] | None = None,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> list[ScoredChunk]:
        # websearch_to_tsquery accepts any text without raising syntax errors (it understands
        # "quoted phrases", -excluded and OR), which matters because the query is user input.
        # It joins plain words with AND, which is too strict for a natural-language question
        # (one word the document happens to lack would match nothing), so the ANDs become
        # ORs and ts_rank_cd ranks chunks by how many of the words occur, and how close
        # together. Stop words ("the", "must", "every") are dropped by the English config.
        parsed = func.websearch_to_tsquery("english", query)
        any_word = cast(func.replace(cast(parsed, Text), " & ", " | "), TSQUERY)
        rank = func.ts_rank_cd(DocumentChunk.search_vector, any_word)
        distance = DocumentChunk.embedding.cosine_distance(list(query_embedding))

        statement = restrict_chunks(
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.page_number,
                DocumentChunk.content,
                distance.label("distance"),
            ).where(DocumentChunk.search_vector.op("@@")(any_word)),
            user_id=user_id,
            document_ids=document_ids,
            content_types=content_types,
            page_from=page_from,
            page_to=page_to,
        )
        # The id breaks ties so equal ranks always come back in the same order.
        statement = statement.order_by(rank.desc(), DocumentChunk.id).limit(limit)

        rows = (await self._session.execute(statement)).all()
        return [
            ScoredChunk(
                chunk_id=row.id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                content=row.content,
                # A chunk without a vector (not embedded yet) has no similarity at all.
                score=0.0 if row.distance is None else 1.0 - float(row.distance),
            )
            for row in rows
        ]
