import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import MessageRole, MessageSource
from app.schemas.ask import MAX_QUESTION_CHARS
from app.services.chat import Exchange, StoredMessage

MAX_TITLE_CHARS = 200

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_CHARS)
]


class ConversationCreate(BaseModel):
    # Optional: an untitled conversation is named after its first question.
    title: Title | None = None


class ConversationUpdate(BaseModel):
    title: Title


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationRead]
    total: int = Field(description="Number of conversations the user has, ignoring paging.")
    limit: int
    offset: int


class SourceRead(BaseModel):
    """A citation saved with an assistant message.

    The passage text is not stored (deleting a document removes its content), so there is
    no excerpt here; ``document_id`` / ``chunk_id`` become null when the document is deleted
    but the filename and page still say where the answer came from."""

    number: int = Field(description="The [number] the message text uses to cite this passage.")
    document_id: uuid.UUID | None
    chunk_id: uuid.UUID | None
    filename: str
    page_number: int | None
    score: float

    @classmethod
    def from_model(cls, source: MessageSource) -> "SourceRead":
        return cls(
            number=source.position,
            document_id=source.document_id,
            chunk_id=source.chunk_id,
            filename=source.document_filename,
            page_number=source.page_number,
            score=source.score,
        )


class MessageRead(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    sources: list[SourceRead]

    @classmethod
    def from_stored(cls, stored: StoredMessage) -> "MessageRead":
        message = stored.message
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            sources=[SourceRead.from_model(s) for s in stored.sources],
        )


class MessageList(BaseModel):
    items: list[MessageRead]
    total: int = Field(description="Number of messages in the conversation, ignoring paging.")
    limit: int
    offset: int


class SendMessageRequest(BaseModel):
    content: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS),
    ]
    # Restrict the answer to these documents. Ids that are not the caller's match nothing.
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class ChatResponse(BaseModel):
    user_message: MessageRead
    assistant_message: MessageRead
    # False when the documents did not contain the answer, or the model cited nothing.
    grounded: bool

    @classmethod
    def from_exchange(cls, exchange: Exchange) -> "ChatResponse":
        return cls(
            user_message=MessageRead.from_stored(exchange.user_message),
            assistant_message=MessageRead.from_stored(exchange.assistant_message),
            grounded=exchange.grounded,
        )
