import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import DocumentStatus


class DocumentRead(BaseModel):
    """What the client may know about a document.

    Deliberately omits the storage path and the content hash: they are internal.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    error_message: str | None
    total_pages: int | None
    total_chunks: int | None
    created_at: datetime
    updated_at: datetime


class DocumentStatusRead(BaseModel):
    """The small payload a client polls while a document is processed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: DocumentStatus
    error_message: str | None
    total_pages: int | None
    total_chunks: int | None


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int = Field(description="Number of documents the user has, ignoring paging.")
    limit: int
    offset: int
