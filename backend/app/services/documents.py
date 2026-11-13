"""Document use cases: upload, list, inspect, retry, delete.

Depends only on small interfaces (``DocumentStore``, ``FileStorage``, ``IngestionQueue``,
``Transaction``) so it can be tested with in-memory fakes. Every method takes the
``user_id`` of the authenticated caller and passes it to every lookup, so one user can
never read or change another user's document, and a foreign id is reported as "not found".
"""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.ingestion.validation import validate_upload
from app.models import Document, DocumentStatus
from app.services.auth import Transaction
from app.services.queue import IngestionQueue
from app.services.storage import FileStorage

logger = logging.getLogger(__name__)

_ENQUEUE_FAILED = "Processing could not be started. Use retry to try again."
_DUPLICATE = "You have already uploaded this file."


class DocumentStore(Protocol):
    async def add(self, document: Document) -> Document: ...

    async def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document | None: ...

    async def get_by_hash(self, user_id: uuid.UUID, content_sha256: str) -> Document | None: ...

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Document]: ...

    async def count_for_user(self, user_id: uuid.UUID) -> int: ...

    async def delete(self, document: Document) -> None: ...


class DocumentService:
    def __init__(
        self,
        *,
        documents: DocumentStore,
        storage: FileStorage,
        queue: IngestionQueue,
        transaction: Transaction,
        settings: Settings,
    ) -> None:
        self._documents = documents
        self._storage = storage
        self._queue = queue
        self._tx = transaction
        self._settings = settings

    async def upload(self, *, user_id: uuid.UUID, filename: str | None, data: bytes) -> Document:
        # Validation parses the file header (and the ZIP index for DOCX), so keep it off
        # the event loop.
        validated = await asyncio.to_thread(
            validate_upload, filename, data, max_bytes=self._settings.max_upload_bytes
        )
        digest = hashlib.sha256(data).hexdigest()
        if await self._documents.get_by_hash(user_id, digest) is not None:
            raise ConflictError(_DUPLICATE)

        document_id = uuid.uuid4()
        path = await self._storage.save(
            user_id=user_id,
            document_id=document_id,
            extension=validated.extension,
            data=data,
        )
        document = Document(
            id=document_id,
            user_id=user_id,
            filename=validated.display_name,
            content_type=validated.content_type,
            size_bytes=len(data),
            storage_path=path,
            content_sha256=digest,
            status=DocumentStatus.PENDING,
        )
        try:
            await self._documents.add(document)
            await self._tx.commit()
        except IntegrityError:
            # Lost a race with a concurrent upload of the same file.
            await self._tx.rollback()
            await self._discard_file(path)
            raise ConflictError(_DUPLICATE) from None
        except BaseException:
            await self._tx.rollback()
            await self._discard_file(path)
            raise

        await self._enqueue(document)
        return document

    async def list(
        self, *, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[Sequence[Document], int]:
        items = await self._documents.list_for_user(user_id, limit=limit, offset=offset)
        return items, await self._documents.count_for_user(user_id)

    async def get(self, *, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self._documents.get(user_id, document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def retry(self, *, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.get(user_id=user_id, document_id=document_id)
        if document.status != DocumentStatus.FAILED:
            raise ConflictError("Only documents that failed can be retried.")
        document.status = DocumentStatus.PENDING
        document.error_message = None
        await self._tx.commit()
        await self._enqueue(document)
        return document

    async def delete(self, *, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        document = await self.get(user_id=user_id, document_id=document_id)
        path = document.storage_path
        await self._documents.delete(document)
        await self._tx.commit()
        # After the commit, so a failure here leaves an orphaned file (harmless, and
        # logged) rather than a database row pointing at a file that is gone.
        await self._discard_file(path)

    async def _enqueue(self, document: Document) -> None:
        try:
            await self._queue.enqueue(document.id)
        except Exception:
            # The broker is unreachable. Do not leave the document "pending" forever with
            # nothing that will ever process it: say so, and let the user retry.
            logger.exception("could not enqueue ingestion for document %s", document.id)
            document.status = DocumentStatus.FAILED
            document.error_message = _ENQUEUE_FAILED
            await self._tx.commit()

    async def _discard_file(self, path: str) -> None:
        try:
            await self._storage.delete(path)
        except OSError:
            logger.exception("could not delete stored file %s", path)
