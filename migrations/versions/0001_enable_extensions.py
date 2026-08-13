"""Enable RDS-compatible PostgreSQL extensions.

Revision ID: 0001_enable_extensions
Revises: None
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0001_enable_extensions"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
