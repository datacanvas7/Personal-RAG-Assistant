"""What the user may change about their own experience, and what the server decides.

Only things that are safe and meaningful per user live here: the theme and how much the
search is allowed to bring back. The language model, the embedding model and the chunking
are server decisions (they carry keys and require re-indexing); the Settings page shows
them read-only.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings
from app.models import Theme
from app.services.auth import Transaction


@dataclass(frozen=True)
class UserPreferences:
    theme: str
    # None = use the server default.
    retrieval_top_k: int | None
    retrieval_score_threshold: float | None


@dataclass(frozen=True)
class RetrievalSettings:
    top_k: int
    score_threshold: float


DEFAULT_PREFERENCES = UserPreferences(
    theme=Theme.SYSTEM.value, retrieval_top_k=None, retrieval_score_threshold=None
)


class SettingsStore(Protocol):
    async def get(self, user_id: uuid.UUID) -> UserPreferences | None: ...

    async def upsert(self, user_id: uuid.UUID, values: Mapping[str, Any]) -> UserPreferences: ...


class SettingsService:
    def __init__(
        self, *, store: SettingsStore, transaction: Transaction, settings: Settings
    ) -> None:
        self._store = store
        self._tx = transaction
        self._settings = settings

    async def get(self, *, user_id: uuid.UUID) -> UserPreferences:
        return await self._store.get(user_id) or DEFAULT_PREFERENCES

    async def update(self, *, user_id: uuid.UUID, changes: Mapping[str, Any]) -> UserPreferences:
        """Apply only the given fields. A retrieval field set to None goes back to the server
        default."""
        if not changes:
            return await self.get(user_id=user_id)
        saved = await self._store.upsert(user_id, changes)
        await self._tx.commit()
        return saved

    async def retrieval(self, *, user_id: uuid.UUID) -> RetrievalSettings:
        """The numbers a search for this user must use: their own or the server's."""
        preferences = await self.get(user_id=user_id)
        return RetrievalSettings(
            top_k=preferences.retrieval_top_k or self._settings.retrieval_top_k,
            score_threshold=(
                self._settings.retrieval_score_threshold
                if preferences.retrieval_score_threshold is None
                else preferences.retrieval_score_threshold
            ),
        )
