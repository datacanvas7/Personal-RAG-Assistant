"""The WHERE clauses shared by every chunk query (vector and keyword).

Keeping them in one place means the ownership rule cannot differ between the two halves of
hybrid search: both always filter on ``user_id`` first, and both treat the optional metadata
filters identically.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select

from app.models import Document, DocumentChunk


def restrict_chunks[T: tuple[Any, ...]](
    statement: Select[T],
    *,
    user_id: uuid.UUID,
    document_ids: Sequence[uuid.UUID] | None = None,
    content_types: Sequence[str] | None = None,
    page_from: int | None = None,
    page_to: int | None = None,
) -> Select[T]:
    """Limit a ``document_chunks`` query to the caller's chunks and the requested subset.

    ``document_ids`` that are not the caller's (or do not exist) match nothing, because the
    ``user_id`` condition is always present as well. ``page_from``/``page_to`` are inclusive
    and exclude chunks without a page number (formats such as TXT have none).
    """
    statement = statement.where(DocumentChunk.user_id == user_id)
    if document_ids is not None:
        statement = statement.where(DocumentChunk.document_id.in_(document_ids))
    if content_types:
        owned_of_type = select(Document.id).where(
            Document.user_id == user_id, Document.content_type.in_(content_types)
        )
        statement = statement.where(DocumentChunk.document_id.in_(owned_of_type))
    if page_from is not None:
        statement = statement.where(DocumentChunk.page_number >= page_from)
    if page_to is not None:
        statement = statement.where(DocumentChunk.page_number <= page_to)
    return statement
