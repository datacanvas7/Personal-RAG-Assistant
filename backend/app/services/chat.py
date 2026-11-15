"""Chat use cases: conversations, saved messages, and answering a question inside one.

Depends only on small interfaces (``ConversationStore``, ``MessageStore``, ``Transaction``)
and on ``RagService``, so it can be tested with in-memory fakes. Every method takes the
``user_id`` of the authenticated caller and passes it to every lookup: a conversation of
another user is reported as "not found", exactly like one that does not exist.

Saving rule: a question and its answer are stored together, in one transaction, after the
answer is complete. If generation fails (model down, client gone) nothing is stored, so there
are no dangling questions and the client can simply retry. No database transaction is open
while the model is generating (``RagService`` releases it right after retrieval).
"""

import logging
import uuid
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.errors import NotFoundError
from app.llm.base import ChatMessage
from app.models import Conversation, Message, MessageRole, MessageSource
from app.rag.service import Answer, RagService, StreamFinished, TextPiece
from app.services.auth import Transaction

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "New conversation"
_TITLE_CHARS = 60
_NOT_FOUND = "Conversation not found."


class ConversationStore(Protocol):
    async def add(self, conversation: Conversation) -> Conversation: ...

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None: ...

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Conversation]: ...

    async def count_for_user(self, user_id: uuid.UUID) -> int: ...

    async def touch(
        self, conversation: Conversation, *, at: datetime, title: str | None = None
    ) -> Conversation: ...

    async def delete(self, conversation: Conversation) -> None: ...


class MessageStore(Protocol):
    async def add_all(
        self, messages: Sequence[Message], sources: Sequence[MessageSource]
    ) -> None: ...

    async def list_for_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Message]: ...

    async def count_for_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> int: ...

    async def recent(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int
    ) -> Sequence[Message]: ...

    async def sources_for(
        self, user_id: uuid.UUID, message_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[MessageSource]]: ...


@dataclass(frozen=True)
class StoredMessage:
    message: Message
    sources: list[MessageSource]


@dataclass(frozen=True)
class Exchange:
    """One question and the answer to it, as saved."""

    user_message: StoredMessage
    assistant_message: StoredMessage
    # True when the answer is built on cited passages of the user's documents.
    grounded: bool


@dataclass(frozen=True)
class TokenEvent:
    """A piece of the answer, a preview: ``DoneEvent`` carries the final text."""

    text: str


@dataclass(frozen=True)
class DoneEvent:
    exchange: Exchange


ChatEvent = TokenEvent | DoneEvent


def _title_from(question: str) -> str:
    one_line = " ".join(question.split())
    if len(one_line) <= _TITLE_CHARS:
        return one_line
    return one_line[: _TITLE_CHARS - 1].rstrip() + "…"


def _as_history(messages: Sequence[Message]) -> list[ChatMessage]:
    return [
        ChatMessage("user" if m.role == MessageRole.USER else "assistant", m.content)
        for m in messages
    ]


class ChatService:
    def __init__(
        self,
        *,
        conversations: ConversationStore,
        messages: MessageStore,
        rag: RagService,
        transaction: Transaction,
        history_max_messages: int,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._rag = rag
        self._tx = transaction
        self._history_max = history_max_messages

    # --- Conversations --------------------------------------------------------------

    async def create_conversation(self, *, user_id: uuid.UUID, title: str | None) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title or DEFAULT_TITLE)
        await self._conversations.add(conversation)
        await self._tx.commit()
        return conversation

    async def list_conversations(
        self, *, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[Sequence[Conversation], int]:
        items = await self._conversations.list_for_user(user_id, limit=limit, offset=offset)
        return items, await self._conversations.count_for_user(user_id)

    async def get_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await self._conversations.get(user_id, conversation_id)
        if conversation is None:
            raise NotFoundError(_NOT_FOUND)
        return conversation

    async def rename_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, title: str
    ) -> Conversation:
        conversation = await self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        await self._conversations.touch(conversation, at=datetime.now(UTC), title=title)
        await self._tx.commit()
        return conversation

    async def delete_conversation(self, *, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        conversation = await self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        await self._conversations.delete(conversation)
        await self._tx.commit()

    # --- Messages -------------------------------------------------------------------

    async def list_messages(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[StoredMessage], int]:
        await self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        messages = await self._messages.list_for_conversation(
            user_id, conversation_id, limit=limit, offset=offset
        )
        sources = await self._messages.sources_for(user_id, [m.id for m in messages])
        total = await self._messages.count_for_conversation(user_id, conversation_id)
        return [StoredMessage(m, sources.get(m.id, [])) for m in messages], total

    async def send(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> Exchange:
        """Answer ``content`` inside the conversation and save both messages."""
        received_at = datetime.now(UTC)
        conversation, history = await self._load(user_id, conversation_id)
        answer = await self._rag.answer(
            user_id=user_id, question=content, history=history, document_ids=document_ids
        )
        return await self._save(user_id, conversation, content, answer, received_at)

    async def stream(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> AsyncGenerator[ChatEvent]:
        """Like ``send``, but yields ``TokenEvent`` pieces first and ``DoneEvent`` last.

        Errors that happen before the first event (unknown conversation, no model
        configured, retrieval failing) are raised by the first ``__anext__`` call, so the
        HTTP layer can still answer with a proper status code."""
        received_at = datetime.now(UTC)
        conversation, history = await self._load(user_id, conversation_id)
        final: Answer | None = None
        async for event in self._rag.stream_answer(
            user_id=user_id, question=content, history=history, document_ids=document_ids
        ):
            if isinstance(event, TextPiece):
                yield TokenEvent(event.text)
            elif isinstance(event, StreamFinished):
                final = event.answer
        if final is None:  # pragma: no cover - stream_answer always finishes or raises
            raise RuntimeError("answer stream ended without a result")
        yield DoneEvent(await self._save(user_id, conversation, content, final, received_at))

    # --- Internals ------------------------------------------------------------------

    async def _load(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> tuple[Conversation, list[ChatMessage]]:
        conversation = await self.get_conversation(user_id=user_id, conversation_id=conversation_id)
        recent = await self._messages.recent(user_id, conversation_id, limit=self._history_max)
        return conversation, _as_history(recent)

    async def _save(
        self,
        user_id: uuid.UUID,
        conversation: Conversation,
        question: str,
        answer: Answer,
        received_at: datetime,
    ) -> Exchange:
        # The question is stamped with the time it was received, the answer with the time it
        # was finished (never earlier than the question: a coarse clock must not reorder them).
        answered_at = max(datetime.now(UTC), received_at + timedelta(microseconds=1))
        user_message = Message(
            id=uuid.uuid4(),
            user_id=user_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=question,
            created_at=received_at,
        )
        assistant_message = Message(
            id=uuid.uuid4(),
            user_id=user_id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=answer.text,
            created_at=answered_at,
        )
        sources = [
            MessageSource(
                id=uuid.uuid4(),
                user_id=user_id,
                message_id=assistant_message.id,
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                position=source.number,
                document_filename=source.filename,
                page_number=source.page_number,
                score=source.score,
                created_at=answered_at,
            )
            for source in answer.sources
        ]
        title = _title_from(question) if conversation.title == DEFAULT_TITLE else None
        try:
            await self._messages.add_all([user_message, assistant_message], sources)
            await self._conversations.touch(conversation, at=answered_at, title=title)
            await self._tx.commit()
        except IntegrityError:
            # The conversation was deleted while the answer was being written.
            await self._tx.rollback()
            raise NotFoundError(_NOT_FOUND) from None
        except Exception:
            await self._tx.rollback()
            raise
        return Exchange(
            user_message=StoredMessage(user_message, []),
            assistant_message=StoredMessage(assistant_message, sources),
            grounded=answer.grounded,
        )
