"""The ingestion job: claim a document, extract its text, embed it, store its chunks.

Written against small interfaces (``IngestionStore``, ``FileStorage``, ``EmbeddingProvider``)
so the failure paths can be tested without a database, a file system, a model or a worker.
"""

import logging
import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from app.core.config import Settings
from app.embeddings.base import EmbeddingError, EmbeddingProvider, EmbeddingUnavailableError
from app.ingestion.chunking import Chunk, chunk_pages
from app.ingestion.cleaning import clean_text
from app.ingestion.errors import IngestionError
from app.ingestion.loaders import LoadedDocument, LoadLimits, PageText, load_document
from app.repositories.documents import ClaimedDocument
from app.services.storage import FileStorage

logger = logging.getLogger(__name__)

_UNEXPECTED_FAILURE = "The document could not be processed. Please try again or contact support."
_EMBEDDING_FAILURE = (
    "The document could not be indexed for search. Please try again later or contact support."
)


class IngestionStore(Protocol):
    def claim(self, document_id: uuid.UUID) -> ClaimedDocument | None: ...

    def replace_chunks(
        self,
        document_id: uuid.UUID,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        *,
        embedding_model: str,
        total_pages: int | None,
    ) -> bool: ...

    def mark_failed(self, document_id: uuid.UUID, message: str) -> None: ...


class IngestionOutcome(StrEnum):
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"  # nothing to do: deleted, or already processed


def run_ingestion(
    document_id: uuid.UUID,
    *,
    store: IngestionStore,
    storage: FileStorage,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> IngestionOutcome:
    """Process one document.

    Safe to run any number of times for the same document: a second run either skips it
    or replaces its chunks wholesale. Problems with the file itself end the job as
    ``failed`` with a user-facing message (retrying cannot help). Problems that may pass,
    a database outage or an unreachable embedding service, are not caught here; they
    propagate so the task can retry them.
    """
    claimed = store.claim(document_id)
    if claimed is None:
        logger.info("ingestion skipped: document %s not pending", document_id)
        return IngestionOutcome.SKIPPED

    try:
        loaded = _load_and_clean(claimed, storage, settings)
        chunks = chunk_pages(
            loaded.pages,
            size=settings.chunk_size_chars,
            overlap=settings.chunk_overlap_chars,
        )
        if not chunks:
            raise IngestionError("No text could be extracted from this document.")
        # Embedding runs before the database transaction opens, so a slow model or API
        # never holds a lock.
        vectors = _embed(embedder, chunks)
    except IngestionError as error:
        logger.info("ingestion failed for %s: %s", document_id, error)
        store.mark_failed(document_id, str(error))
        return IngestionOutcome.FAILED
    except EmbeddingUnavailableError:
        raise  # transient: the task retries, the document stays "processing"
    except EmbeddingError:
        logger.exception("embedding failed for %s", document_id)
        store.mark_failed(document_id, _EMBEDDING_FAILURE)
        return IngestionOutcome.FAILED
    except Exception:
        # A bug or an unforeseen file: log the details for us, show something generic.
        logger.exception("ingestion crashed for %s", document_id)
        store.mark_failed(document_id, _UNEXPECTED_FAILURE)
        return IngestionOutcome.FAILED

    if not store.replace_chunks(
        document_id,
        chunks,
        vectors,
        embedding_model=embedder.model_id,
        total_pages=loaded.total_pages,
    ):
        logger.info("document %s was deleted during ingestion", document_id)
        return IngestionOutcome.SKIPPED
    logger.info("ingested %s: %d chunks", document_id, len(chunks))
    return IngestionOutcome.READY


def _embed(embedder: EmbeddingProvider, chunks: Sequence[Chunk]) -> list[list[float]]:
    vectors = embedder.embed_documents([chunk.content for chunk in chunks])
    # A provider bug must not silently misalign vectors and chunks.
    if len(vectors) != len(chunks) or any(len(v) != embedder.dimension for v in vectors):
        raise EmbeddingError("the embedding provider returned vectors of the wrong number or size")
    return vectors


def _load_and_clean(
    claimed: ClaimedDocument, storage: FileStorage, settings: Settings
) -> LoadedDocument:
    try:
        path = storage.resolve(claimed.storage_path)
        loaded = load_document(
            path,
            claimed.extension,
            LoadLimits(
                max_pdf_pages=settings.max_pdf_pages,
                max_extracted_chars=settings.max_extracted_chars,
                ocr_min_chars_per_page=settings.ocr_min_chars_per_page,
            ),
        )
    except FileNotFoundError:
        raise IngestionError("The uploaded file is missing. Please upload it again.") from None
    return LoadedDocument(
        pages=[PageText(page.page_number, clean_text(page.text)) for page in loaded.pages],
        total_pages=loaded.total_pages,
    )
