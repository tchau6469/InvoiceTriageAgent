"""Include document titles in generated lexical vectors.

Revision ID: 0005_title_search
Revises: 0004_search_indexes
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0005_title_search"
down_revision: str | None = "0004_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX ix_document_chunks_search_vector_gin")
    op.execute("ALTER TABLE document_chunks DROP COLUMN search_vector")
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS (
            setweight(
                to_tsvector(
                    'english',
                    coalesce(metadata ->> 'document_title', '')
                ),
                'A'
            )
            || setweight(to_tsvector('english', coalesce(section, '')), 'A')
            || setweight(to_tsvector('english', coalesce(content, '')), 'B')
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_search_vector_gin
        ON document_chunks USING GIN (search_vector)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_document_chunks_search_vector_gin")
    op.execute("ALTER TABLE document_chunks DROP COLUMN search_vector")
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(section, '')), 'A')
            || setweight(to_tsvector('english', coalesce(content, '')), 'B')
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_search_vector_gin
        ON document_chunks USING GIN (search_vector)
        """
    )
