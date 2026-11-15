"""Read-only aggregate counts for the dashboard. Everything is scoped to one user."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    Document,
    DocumentChunk,
    DocumentStatus,
    Message,
    MessageRole,
    MessageSource,
)


@dataclass(frozen=True)
class OverviewCounts:
    documents_by_status: dict[DocumentStatus, int]
    chunks: int
    conversations: int
    user_messages: int
    assistant_messages: int
    # Assistant answers that cite at least one source (the rest said "not found" or cited none).
    cited_answers: int
    documents_since: int
    conversations_since: int
    questions_since: int


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _scalar(self, statement: Select[Any]) -> int:
        return int((await self._session.execute(statement)).scalar_one())

    async def overview(self, user_id: uuid.UUID, *, since: datetime) -> OverviewCounts:
        status_rows = await self._session.execute(
            select(Document.status, func.count())
            .where(Document.user_id == user_id)
            .group_by(Document.status)
        )
        by_status = {DocumentStatus(status): count for status, count in status_rows.all()}

        message_rows = await self._session.execute(
            select(Message.role, func.count())
            .where(Message.user_id == user_id)
            .group_by(Message.role)
        )
        by_role = {MessageRole(role): count for role, count in message_rows.all()}

        return OverviewCounts(
            documents_by_status=by_status,
            chunks=await self._scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.user_id == user_id)
            ),
            conversations=await self._scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.user_id == user_id)
            ),
            user_messages=by_role.get(MessageRole.USER, 0),
            assistant_messages=by_role.get(MessageRole.ASSISTANT, 0),
            cited_answers=await self._scalar(
                select(func.count(func.distinct(MessageSource.message_id))).where(
                    MessageSource.user_id == user_id
                )
            ),
            documents_since=await self._scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.user_id == user_id, Document.created_at >= since)
            ),
            conversations_since=await self._scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.user_id == user_id, Conversation.created_at >= since)
            ),
            questions_since=await self._scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.user_id == user_id,
                    Message.role == MessageRole.USER,
                    Message.created_at >= since,
                )
            ),
        )
