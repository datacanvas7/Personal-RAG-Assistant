from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from app.core.config import get_settings
from app.db.base import Base
from app.models import *  # noqa: F403  (registers the models on Base.metadata)
from tests.integration.conftest import alembic_config, reset_schema

EXPECTED_TABLES = {
    "users",
    "refresh_tokens",
    "documents",
    "document_chunks",
    "conversations",
    "messages",
    "message_sources",
}


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_upgrade_creates_every_table(migrated_engine: Engine) -> None:
    assert _tables(migrated_engine) == EXPECTED_TABLES


def test_migration_matches_the_models(migrated_engine: Engine) -> None:
    """Fails when someone changes a model without writing a migration (or vice versa)."""
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": False})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_embedding_column_has_the_configured_dimension(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        column_type = conn.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()

    assert column_type == f"vector({get_settings().embedding_dimension})"


def test_downgrade_then_upgrade_again_works(engine: Engine) -> None:
    reset_schema(engine)
    command.upgrade(alembic_config(), "head")
    command.downgrade(alembic_config(), "base")
    assert _tables(engine) == set()

    command.upgrade(alembic_config(), "head")
    assert _tables(engine) == EXPECTED_TABLES
