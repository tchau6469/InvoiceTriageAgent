"""Create relational, full-text, and vector search indexes.

Revision ID: 0004_search_indexes
Revises: 0003_rag_tables
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0004_search_indexes"
down_revision: str | None = "0003_rag_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_vendors_category_status ON vendors (category, status)")
    op.execute("CREATE INDEX ix_vendors_aliases_gin ON vendors USING GIN (aliases)")
    op.execute(
        "CREATE INDEX ix_monthly_budgets_lookup "
        "ON monthly_budgets (budget_period, cost_center, category)"
    )
    op.execute(
        "CREATE INDEX ix_source_documents_scope "
        "ON source_documents (document_type, category, vendor_id, status)"
    )
    op.execute(
        "CREATE INDEX ix_source_documents_metadata_gin "
        "ON source_documents USING GIN (metadata jsonb_path_ops)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_scope "
        "ON document_chunks (document_type, category, vendor_id, status)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_metadata_gin "
        "ON document_chunks USING GIN (metadata jsonb_path_ops)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_search_vector_gin "
        "ON document_chunks USING GIN (search_vector)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING HNSW (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_vector_gin")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_metadata_gin")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_scope")
    op.execute("DROP INDEX IF EXISTS ix_source_documents_metadata_gin")
    op.execute("DROP INDEX IF EXISTS ix_source_documents_scope")
    op.execute("DROP INDEX IF EXISTS ix_monthly_budgets_lookup")
    op.execute("DROP INDEX IF EXISTS ix_vendors_aliases_gin")
    op.execute("DROP INDEX IF EXISTS ix_vendors_category_status")
