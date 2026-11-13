"""Database engine and session factory."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

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


# --- Synchronous access, for the Celery worker -------------------------------------------
# Celery tasks are plain functions run in worker processes, not coroutines, so they use a
# synchronous engine (the same psycopg driver). It is created lazily, inside the worker
# process, after Celery has forked.


@lru_cache
def get_sync_engine() -> Engine:
    # connect_timeout: a startup check must fail fast, not hang, when the database is down.
    return create_engine(
        get_settings().database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10}
    )


def get_sync_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_sync_engine(), expire_on_commit=False)
