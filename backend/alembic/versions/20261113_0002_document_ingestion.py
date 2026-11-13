"""Document ingestion: page/chunk counters and one-upload-per-file uniqueness.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("total_pages", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("total_chunks", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_documents_user_id_content_sha256", "documents", ["user_id", "content_sha256"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_user_id_content_sha256", "documents", type_="unique")
    op.drop_column("documents", "total_chunks")
    op.drop_column("documents", "total_pages")
