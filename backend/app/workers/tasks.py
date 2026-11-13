import logging
import uuid
from typing import Any

from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.session import get_sync_sessionmaker
from app.ingestion.pipeline import run_ingestion
from app.repositories.documents import SqlIngestionStore
from app.services.queue import INGEST_TASK_NAME
from app.services.storage import LocalFileStorage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 5


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check proving that broker, worker and result backend are connected."""
    return "pong"


@celery_app.task(name=INGEST_TASK_NAME, bind=True, max_retries=_MAX_RETRIES)
def ingest_document(self: Any, document_id: str) -> str:
    """Extract, chunk and store one document.

    Problems with the file end the job as ``failed`` inside ``run_ingestion``. A database
    outage is retried with exponential backoff; the job is idempotent, so a retry (or a
    redelivery after a worker crash, since tasks are acknowledged late) is harmless.
    """
    settings = get_settings()
    parsed_id = uuid.UUID(document_id)
    with get_sync_sessionmaker()() as session:
        store = SqlIngestionStore(session)
        try:
            outcome = run_ingestion(
                parsed_id,
                store=store,
                storage=LocalFileStorage(settings.upload_dir),
                settings=settings,
            )
        except OperationalError as error:
            if self.request.retries >= _MAX_RETRIES:
                logger.exception("giving up on document %s", document_id)
                store.mark_failed(
                    parsed_id, "Processing failed repeatedly. Please try again later."
                )
                return "failed"
            raise self.retry(
                exc=error, countdown=_RETRY_BASE_SECONDS * 2**self.request.retries
            ) from error
    return outcome.value
