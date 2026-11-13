"""Database access for documents and their chunks. No business rules live here.

Every read that serves a user filters on ``user_id`` in SQL. The ingestion store is the one
exception: the worker acts on a document id it received from the queue, which only the API
can have put there after checking ownership.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.ingestion.chunking import Chunk
from app.models import Document, DocumentChunk, DocumentStatus


class DocumentRepository:
    """Used by the API (async)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: Document) -> Document:
        """Insert now (not at commit) so a duplicate upload surfaces as IntegrityError here."""
        self._session.add(document)
        await self._session.flush()
        return document

    async def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        result = await self._session.execute(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, user_id: uuid.UUID, content_sha256: str) -> Document | None:
        result = await self._session.execute(
            select(Document).where(
                Document.user_id == user_id, Document.content_sha256 == content_sha256
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Document]:
        result = await self._session.execute(
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc(), Document.id)
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Document).where(Document.user_id == user_id)
        )
        return result.scalar_one()

    async def delete(self, document: Document) -> None:
        # Chunks go with it through ON DELETE CASCADE.
        await self._session.delete(document)
        await self._session.flush()


@dataclass(frozen=True)
class ClaimedDocument:
    id: uuid.UUID
    user_id: uuid.UUID
    storage_path: str
    extension: str


class SqlIngestionStore:
    """Used by the Celery worker (sync). Each method is one short transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def claim(self, document_id: uuid.UUID) -> ClaimedDocument | None:
        """Mark a document as being processed; ``None`` if there is nothing to do.

        ``pending`` is the normal case, ``failed`` is a user-requested retry, and
        ``processing`` is a redelivery after a worker died mid-task. A document that is
        already ``ready`` (a duplicate delivery) or no longer exists is skipped.
        """
        row = self._session.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.status.in_(
                    [DocumentStatus.PENDING, DocumentStatus.FAILED, DocumentStatus.PROCESSING]
                ),
            )
            .values(status=DocumentStatus.PROCESSING, error_message=None)
            .returning(Document.id, Document.user_id, Document.storage_path)
        ).one_or_none()
        self._session.commit()
        if row is None:
            return None
        extension = "." + row.storage_path.rsplit(".", 1)[-1]
        return ClaimedDocument(row.id, row.user_id, row.storage_path, extension)

    def replace_chunks(
        self, document_id: uuid.UUID, chunks: Sequence[Chunk], *, total_pages: int | None
    ) -> bool:
        """Atomically swap in a document's chunks and mark it ``ready``.

        Old chunks are deleted and new ones inserted in one transaction while the document
        row is locked, so a crash, a retry or two racing workers can never leave a partial
        or duplicated set. Returns ``False`` if the document was deleted meanwhile.
        """
        document = self._session.execute(
            select(Document).where(Document.id == document_id).with_for_update()
        ).scalar_one_or_none()
        if document is None:
            self._session.rollback()
            return False

        self._session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        self._session.execute(
            insert(DocumentChunk),
            [
                {
                    "user_id": document.user_id,
                    "document_id": document_id,
                    "chunk_index": chunk.index,
                    "content": chunk.content,
                    "page_number": chunk.page_number,
                }
                for chunk in chunks
            ],
        )
        document.status = DocumentStatus.READY
        document.error_message = None
        document.total_pages = total_pages
        document.total_chunks = len(chunks)
        self._session.commit()
        return True

    def mark_failed(self, document_id: uuid.UUID, message: str) -> None:
        self._session.rollback()  # discard anything left open by the failed step
        self._session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.PROCESSING)
            .values(status=DocumentStatus.FAILED, error_message=message[:500])
        )
        self._session.commit()
