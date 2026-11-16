"""Storage of the per-user preferences. Every query is scoped to one user id."""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSettings
from app.services.settings import UserPreferences


def _preferences(row: UserSettings) -> UserPreferences:
    return UserPreferences(
        theme=row.theme,
        retrieval_top_k=row.retrieval_top_k,
        retrieval_score_threshold=row.retrieval_score_threshold,
    )


class UserSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> UserPreferences | None:
        row = await self._session.get(UserSettings, user_id)
        return None if row is None else _preferences(row)

    async def upsert(self, user_id: uuid.UUID, values: Mapping[str, Any]) -> UserPreferences:
        """Create the row or change only the given columns, in one statement, so two first
        saves arriving together cannot collide."""
        statement = (
            insert(UserSettings)
            .values(user_id=user_id, **values)
            .on_conflict_do_update(
                index_elements=[UserSettings.user_id],
                set_={**values, "updated_at": func.now()},
            )
            .returning(UserSettings)
        )
        result = await self._session.execute(
            statement, execution_options={"populate_existing": True}
        )
        return _preferences(result.scalar_one())
