"""The API's engine bounds its connections and stops runaway queries."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.db.session import get_engine


@pytest.fixture
def short_timeout_engine(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "1000")
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield get_engine()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def test_a_statement_that_runs_too_long_is_cancelled(short_timeout_engine) -> None:  # type: ignore[no-untyped-def]
    async with short_timeout_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="statement timeout"):
            await conn.execute(text("SELECT pg_sleep(5)"))

        # The connection is still usable after the cancelled statement.
        await conn.rollback()
        assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1


async def test_the_pool_is_bounded(short_timeout_engine) -> None:  # type: ignore[no-untyped-def]
    pool = short_timeout_engine.pool

    assert pool.size() == 3
    assert pool._max_overflow == 2  # noqa: SLF001
