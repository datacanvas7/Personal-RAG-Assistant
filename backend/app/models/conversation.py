import enum
import uuid

from sqlalchemy import (
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="id_user_id"),
        Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))


class Message(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["conversations.id", "conversations.user_id"],
            ondelete="CASCADE",
            name="fk_messages_conversation_id_conversations",
        ),
        UniqueConstraint("id", "user_id", name="id_user_id"),
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column()
    conversation_id: Mapped[uuid.UUID] = mapped_column()
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            name="role",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    content: Mapped[str] = mapped_column(Text)


class MessageSource(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A citation: which passage an assistant message was based on.

    ``chunk_id`` / ``document_id`` are SET NULL when the source is deleted. The filename and
    page are copied here so an old answer still says *where* it came from, but the passage
    text is deliberately not: deleting a document must remove its content.
    """

    __tablename__ = "message_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id", "user_id"],
            ["messages.id", "messages.user_id"],
            ondelete="CASCADE",
            name="fk_message_sources_message_id_messages",
        ),
        Index("ix_message_sources_message_id", "message_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column()
    message_id: Mapped[uuid.UUID] = mapped_column()
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(Integer)  # citation number shown to the user
    document_filename: Mapped[str] = mapped_column(String(255))
    page_number: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
