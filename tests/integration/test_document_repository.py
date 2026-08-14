"""Live pgvector storage checks for parsed retrieval chunks."""

from __future__ import annotations

import os
from datetime import date

import pytest

from invoice_triage.config import AppSettings
from invoice_triage.domain import (
    DocumentChunk,
    DocumentStatus,
    DocumentType,
    SourceDocument,
    VendorCategory,
)
from invoice_triage.embeddings import DeterministicEmbeddingClient
from invoice_triage.storage import Database, DocumentRepository


pytestmark = pytest.mark.integration


def _integration_enabled() -> bool:
    return os.getenv("INVOICE_TRIAGE_RUN_INTEGRATION") == "1"


@pytest.mark.skipif(not _integration_enabled(), reason="integration database not enabled")
def test_document_upsert_generates_search_vector_and_replaces_stale_chunks() -> None:
    settings = AppSettings.from_environment()
    database = Database.from_settings(settings)
    repository = DocumentRepository()
    embedding_client = DeterministicEmbeddingClient(dimensions=1024)
    document = SourceDocument(
        document_id="POL-INTEGRATION-TEST",
        document_type=DocumentType.SPENDING_POLICY,
        title="Integration Test Policy",
        content="# Integration Test Policy\n\n## Payment terms\n\nPay Net 30.",
        source_path="test/integration-policy.md",
        status=DocumentStatus.ACTIVE,
        category=VendorCategory.CLOUD_SOFTWARE,
        effective_date=date(2026, 1, 1),
    )
    chunks = (
        _chunk(document, "POL-INTEGRATION-TEST:overview", "Overview", 0, "Policy intro."),
        _chunk(
            document,
            "POL-INTEGRATION-TEST:payment-terms",
            "Payment terms",
            1,
            "Valid invoices are payable Net 30.",
        ),
    )
    vectors = embedding_client.embed_documents([chunk.content for chunk in chunks])

    database.open()
    try:
        with database.connection() as connection:
            with connection.transaction(force_rollback=True):
                assert repository.upsert(connection, document, chunks, vectors) == 2
                match = connection.execute(
                    """
                    SELECT count(*) AS count
                    FROM document_chunks
                    WHERE document_id = %s
                      AND search_vector @@ websearch_to_tsquery('english', 'payment terms')
                      AND vector_dims(embedding) = 1024
                    """,
                    (document.document_id,),
                ).fetchone()
                assert match is not None and match["count"] == 1

                # Reordering and removing a section must not violate the
                # ordinal uniqueness constraint or leave an obsolete chunk.
                remaining = chunks[1].model_copy(update={"ordinal": 0})
                assert repository.upsert(
                    connection,
                    document,
                    (remaining,),
                    (vectors[1],),
                ) == 1
                row = connection.execute(
                    """
                    SELECT count(*) AS count, min(ordinal) AS ordinal
                    FROM document_chunks
                    WHERE document_id = %s
                    """,
                    (document.document_id,),
                ).fetchone()
                assert row == {"count": 1, "ordinal": 0}
    finally:
        database.close()


def _chunk(
    document: SourceDocument,
    chunk_id: str,
    section: str,
    ordinal: int,
    content: str,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document.document_id,
        document_type=document.document_type,
        section=section,
        ordinal=ordinal,
        content=content,
        source_path=document.source_path,
        status=document.status,
        category=document.category,
        effective_date=document.effective_date,
        metadata={"document_title": document.title},
    )
