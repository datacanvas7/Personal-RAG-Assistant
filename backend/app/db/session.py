"""Database engine and session factory."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    # Creating the engine opens no connection; that happens on first use.
    # pool_pre_ping replaces connections that the database has closed (e.g. after a
    # Postgres restart) instead of failing the first request that picks one up.
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: after commit, objects stay readable (the API serializes
    # them), instead of triggering a lazy load, which async sessions cannot do.
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request. The service layer decides when to commit; leaving the
    request without committing rolls back."""
    async with get_sessionmaker()() as session:
        yield session
