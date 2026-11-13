import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentStatus(enum.StrEnum):
    PENDING = "pending"  # uploaded, waiting for the worker
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    # Read database-generated values (updated_at) back with the UPDATE itself. Otherwise the
    # attribute is expired after a status change and serializing the document in the async
    # API would try to lazy-load it, which async sessions cannot do.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        # Lets child tables reference (id, user_id) so the database itself refuses a
        # child row whose owner differs from its parent's owner.
        UniqueConstraint("id", "user_id", name="uq_documents_id_user_id"),
        # The same file cannot be uploaded twice by one user (it would double its weight
        # in retrieval). Two users may of course upload the same file.
        UniqueConstraint("user_id", "content_sha256", name="uq_documents_user_id_content_sha256"),
        Index("ix_documents_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Relative to the upload root; never derived from the client's filename.
    storage_path: Mapped[str] = mapped_column(String(512))
    content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DocumentStatus.PENDING,
        server_default=DocumentStatus.PENDING.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    # Filled in by the ingestion worker; NULL until the document has been processed.
    # total_pages stays NULL for formats without pages (TXT, Markdown, DOCX).
    total_pages: Mapped[int | None] = mapped_column(Integer)
    total_chunks: Mapped[int | None] = mapped_column(Integer)
    # Which embedding model produced this document's vectors (EmbeddingProvider.model_id).
    # Vectors from different models are not comparable, so the application refuses to run
    # against an index that mixes them. NULL until the document has been embedded.
    embedding_model: Mapped[str | None] = mapped_column(String(200))


class DocumentChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "user_id"],
            ["documents.id", "documents.user_id"],
            ondelete="CASCADE",
            name="fk_document_chunks_document_id_documents",
        ),
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_id_chunk_index"
        ),
        UniqueConstraint("id", "user_id", name="uq_document_chunks_id_user_id"),
        # Every retrieval filters on user_id first.
        Index("ix_document_chunks_user_id", "user_id"),
        # Approximate nearest-neighbour search by cosine distance. m and ef_construction are
        # pgvector's defaults, which suit a collection of this size; revisit with the
        # Phase 9 evaluation if recall ever looks low.
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    # Denormalized from the document and enforced equal by the composite foreign key.
    user_id: Mapped[uuid.UUID] = mapped_column()
    document_id: Mapped[uuid.UUID] = mapped_column()
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    # NULL until the embedding step has run.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(get_settings().embedding_dimension)
    )
