"""Conversation, message and citation queries.

Every method takes the owner's ``user_id`` and puts it in the SQL ``WHERE`` clause, so a row
that belongs to someone else is indistinguishable from one that does not exist. No business
rules live here (the service layer decides what is allowed).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, MessageSource


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, conversation: Conversation) -> Conversation:
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Conversation]:
        # Most recently active first; id breaks ties so paging is stable.
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
        )
        return result.scalar_one()

    async def touch(
        self, conversation: Conversation, *, at: datetime, title: str | None = None
    ) -> Conversation:
        """Record activity (moves the conversation to the top of the list) and optionally
        rename it."""
        if title is not None:
            conversation.title = title
        conversation.updated_at = at
        await self._session.flush()
        return conversation

    async def delete(self, conversation: Conversation) -> None:
        # Messages and their sources go with it through ON DELETE CASCADE.
        await self._session.delete(conversation)
        await self._session.flush()


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, messages: Sequence[Message], sources: Sequence[MessageSource]) -> None:
        """Insert messages and their citations in the caller's transaction (messages first:
        the sources' foreign key points at them)."""
        self._session.add_all(messages)
        await self._session.flush()
        self._session.add_all(sources)
        await self._session.flush()

    async def list_for_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Message]:
        """Oldest first, like reading the conversation."""
        result = await self._session.execute(
            select(Message)
            .where(Message.user_id == user_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.user_id == user_id, Message.conversation_id == conversation_id)
        )
        return result.scalar_one()

    async def recent(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int
    ) -> Sequence[Message]:
        """The last ``limit`` messages, oldest first (the prompt's history window)."""
        result = await self._session.execute(
            select(Message)
            .where(Message.user_id == user_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def sources_for(
        self, user_id: uuid.UUID, message_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[MessageSource]]:
        """Citations of several messages in one query, ordered by their number."""
        if not message_ids:
            return {}
        result = await self._session.execute(
            select(MessageSource)
            .where(MessageSource.user_id == user_id, MessageSource.message_id.in_(message_ids))
            .order_by(MessageSource.message_id, MessageSource.position)
        )
        grouped: dict[uuid.UUID, list[MessageSource]] = {}
        for source in result.scalars():
            grouped.setdefault(source.message_id, []).append(source)
        return grouped
