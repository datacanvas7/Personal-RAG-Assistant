"""Fixtures for tests that need a real PostgreSQL with pgvector.

These tests **drop and recreate the public schema** of the configured database, so they
refuse to run unless ``POSTGRES_DB`` ends with ``_test``. CI provides such a database;
locally they are skipped, which keeps a developer's real data safe.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_throwaway_database() -> None:
    if not get_settings().postgres_db.endswith("_test"):
        pytest.skip("integration tests need POSTGRES_DB to end with '_test' (set in CI)")


def alembic_config() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


def reset_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(get_settings().database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def migrated_engine(engine: Engine) -> Engine:
    """A sync engine on a database freshly built by the real migrations."""
    reset_schema(engine)
    command.upgrade(alembic_config(), "head")
    return engine
