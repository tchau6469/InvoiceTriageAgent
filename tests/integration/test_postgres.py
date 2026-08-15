"""Integration checks against the migrated PostgreSQL/pgvector service."""

from __future__ import annotations

import os

import pytest

from invoice_triage.config import AppSettings
from invoice_triage.storage.postgres import Database


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("INVOICE_TRIAGE_RUN_INTEGRATION") != "1",
        reason="set INVOICE_TRIAGE_RUN_INTEGRATION=1 to use PostgreSQL",
    ),
]


@pytest.fixture(scope="module")
def database() -> Database:
    db = Database.from_settings(AppSettings.from_environment())
    db.open()
    try:
        yield db
    finally:
        db.close()


def test_database_health_and_vector_extension(database: Database) -> None:
    assert database.check_health()

    with database.connection() as connection:
        row = connection.execute(
            """
            SELECT extversion
            FROM pg_extension
            WHERE extname = 'vector'
            """
        ).fetchone()

    assert row is not None
    assert row["extversion"] == "0.8.2"


def test_database_is_at_alembic_head(database: Database) -> None:
    with database.connection() as connection:
        row = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()

    assert row == {"version_num": "0006_invoice_records"}


def test_expected_tables_and_indexes_exist(database: Database) -> None:
    with database.connection() as connection:
        tables = connection.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename IN (
                  'vendors',
                  'monthly_budgets',
                  'source_documents',
                  'document_chunks',
                  'invoice_records',
                  'invoice_identifiers'
              )
            """
        ).fetchall()
        indexes = connection.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname IN (
                  'ix_document_chunks_search_vector_gin',
                  'ix_document_chunks_embedding_hnsw',
                  'ix_invoice_records_vendor_number',
                  'ix_invoice_records_budget_commitments',
                  'ix_invoice_identifiers_lookup'
              )
            """
        ).fetchall()

    assert {row["tablename"] for row in tables} == {
        "vendors",
        "monthly_budgets",
        "source_documents",
        "document_chunks",
        "invoice_records",
        "invoice_identifiers",
    }
    assert {row["indexname"] for row in indexes} == {
        "ix_document_chunks_search_vector_gin",
        "ix_document_chunks_embedding_hnsw",
        "ix_invoice_records_vendor_number",
        "ix_invoice_records_budget_commitments",
        "ix_invoice_identifiers_lookup",
    }


def test_pgvector_codec_and_full_text_generation(database: Database) -> None:
    with database.connection() as connection:
        vector_row = connection.execute(
            "SELECT '[1,2,3]'::vector AS embedding"
        ).fetchone()
        text_row = connection.execute(
            """
            SELECT to_tsvector(
                'english',
                'Monthly usage charges require authorization'
            ) @@ plainto_tsquery('english', 'authorize usage') AS matches
            """
        ).fetchone()

    assert vector_row is not None
    assert vector_row["embedding"].tolist() == [1.0, 2.0, 3.0]
    assert text_row == {"matches": True}
