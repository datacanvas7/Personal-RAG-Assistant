"""Database engine. Session factories are added in Phase 2 together with the models."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    # Creating the engine opens no connection; that happens on first use.
    # pool_pre_ping replaces connections that the database has closed (e.g. after a
    # Postgres restart) instead of failing the first request that picks one up.
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)
