"""Handing work to the background worker."""

import asyncio
import uuid
from typing import Protocol

INGEST_TASK_NAME = "documents.ingest"


class IngestionQueue(Protocol):
    async def enqueue(self, document_id: uuid.UUID) -> None: ...


def enqueue_ingestion_sync(document_id: uuid.UUID) -> None:
    """Blocking variant for scripts that run outside an event loop."""
    from app.workers.celery_app import celery_app

    celery_app.send_task(INGEST_TASK_NAME, args=[str(document_id)])


class CeleryIngestionQueue:
    async def enqueue(self, document_id: uuid.UUID) -> None:
        # Imported here so that importing the API does not also configure Celery.
        from app.workers.celery_app import celery_app

        # send_task opens a broker connection and blocks; keep it off the event loop. The
        # task is addressed by name so the API never imports the worker's code.
        await asyncio.to_thread(celery_app.send_task, INGEST_TASK_NAME, args=[str(document_id)])
