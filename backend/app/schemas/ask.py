import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

MAX_QUESTION_CHARS = 2000
MAX_HISTORY_MESSAGES = 40
MAX_HISTORY_MESSAGE_CHARS = 4000


class HistoryMessage(BaseModel):
    # No "system" role: the client must not be able to inject instructions of its own.
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(max_length=MAX_HISTORY_MESSAGE_CHARS)]


class AskRequest(BaseModel):
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS),
    ]
    # Earlier turns of this conversation, oldest first. Only the most recent few are used.
    history: list[HistoryMessage] = Field(default_factory=list, max_length=MAX_HISTORY_MESSAGES)
    # Restrict the answer to these documents. Ids that are not the caller's match nothing.
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceOut(BaseModel):
    # The [number] the answer text uses to refer to this passage.
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    excerpt: str
    score: float


class AskResponse(BaseModel):
    answer: str
    # False when the documents did not contain the answer, or the model cited nothing.
    grounded: bool
    sources: list[SourceOut]
