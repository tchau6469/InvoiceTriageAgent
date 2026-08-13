"""Create source-document and retrieval-chunk tables.

Revision ID: 0003_rag_tables
Revises: 0002_structured_tables
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0003_rag_tables"
down_revision: str | None = "0002_structured_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORIES = """
    'cloud_software',
    'office_supplies',
    'facilities_maintenance',
    'professional_services',
    'logistics_freight',
    'marketing_events'
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE source_documents (
            document_id TEXT PRIMARY KEY,
            document_type TEXT NOT NULL
                CHECK (document_type IN (
                    'vendor_contract', 'spending_policy', 'invoice'
                )),
            title TEXT NOT NULL,
            content TEXT NOT NULL CHECK (length(btrim(content)) > 0),
            source_path TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL
                CHECK (status IN ('active', 'expired', 'superseded', 'historical')),
            vendor_id TEXT REFERENCES vendors(vendor_id) ON DELETE RESTRICT,
            category TEXT CHECK (category IS NULL OR category IN ({CATEGORIES})),
            effective_date DATE,
            expiration_date DATE,
            metadata JSONB NOT NULL DEFAULT '{{}}'::JSONB
                CHECK (jsonb_typeof(metadata) = 'object'),
            content_sha256 CHAR(64) NOT NULL
                CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (
                expiration_date IS NULL
                OR effective_date IS NULL
                OR expiration_date >= effective_date
            ),
            CHECK (
                document_type NOT IN ('vendor_contract', 'invoice')
                OR vendor_id IS NOT NULL
            ),
            CHECK (
                document_type NOT IN ('vendor_contract', 'spending_policy')
                OR category IS NOT NULL
            )
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE document_chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL
                REFERENCES source_documents(document_id) ON DELETE CASCADE,
            document_type TEXT NOT NULL
                CHECK (document_type IN (
                    'vendor_contract', 'spending_policy', 'invoice'
                )),
            section TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            content TEXT NOT NULL CHECK (length(btrim(content)) > 0),
            source_path TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('active', 'expired', 'superseded', 'historical')),
            vendor_id TEXT REFERENCES vendors(vendor_id) ON DELETE RESTRICT,
            category TEXT CHECK (category IS NULL OR category IN ({CATEGORIES})),
            effective_date DATE,
            expiration_date DATE,
            metadata JSONB NOT NULL DEFAULT '{{}}'::JSONB
                CHECK (jsonb_typeof(metadata) = 'object'),
            content_sha256 CHAR(64) NOT NULL
                CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
            embedding vector(1024),
            search_vector TSVECTOR GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(section, '')), 'A')
                || setweight(to_tsvector('english', coalesce(content, '')), 'B')
            ) STORED,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (document_id, ordinal),
            CHECK (
                expiration_date IS NULL
                OR effective_date IS NULL
                OR expiration_date >= effective_date
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_chunks")
    op.execute("DROP TABLE IF EXISTS source_documents")
