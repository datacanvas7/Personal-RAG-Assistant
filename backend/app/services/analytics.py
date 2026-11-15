"""The dashboard numbers: how much the user has stored and done."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.models import DocumentStatus
from app.repositories.analytics import OverviewCounts

RECENT_DAYS = 7


class OverviewStore(Protocol):
    async def overview(self, user_id: uuid.UUID, *, since: datetime) -> OverviewCounts: ...


@dataclass(frozen=True)
class Overview:
    counts: OverviewCounts
    recent_days: int

    @property
    def total_documents(self) -> int:
        return sum(self.counts.documents_by_status.values())

    def documents_with_status(self, status: DocumentStatus) -> int:
        return self.counts.documents_by_status.get(status, 0)


class AnalyticsService:
    def __init__(self, *, store: OverviewStore) -> None:
        self._store = store

    async def overview(self, *, user_id: uuid.UUID) -> Overview:
        since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
        return Overview(await self._store.overview(user_id, since=since), RECENT_DAYS)
