"""Live PostgreSQL checks for vector and lexical retrieval SQL."""

from __future__ import annotations

import os
from datetime import date

import pytest

from invoice_triage.config import AppSettings
from invoice_triage.domain import (
    DocumentChunk,
    DocumentStatus,
    DocumentType,
    RetrievalQuery,
    SourceDocument,
    VendorCategory,
)
from invoice_triage.embeddings import DeterministicEmbeddingClient
from invoice_triage.retrieval import KeywordSearcher, VectorSearcher
from invoice_triage.storage import Database, DocumentRepository


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("INVOICE_TRIAGE_RUN_INTEGRATION") != "1",
        reason="set INVOICE_TRIAGE_RUN_INTEGRATION=1 to use PostgreSQL",
    ),
]


def test_vector_and_lexical_search_retrieve_expected_chunk() -> None:
    database = Database.from_settings(AppSettings.from_environment())
    repository = DocumentRepository()
    embedder = DeterministicEmbeddingClient(dimensions=1024)
    document = SourceDocument(
        document_id="POL-RETRIEVAL-INTEGRATION",
        document_type=DocumentType.SPENDING_POLICY,
        title="Retrieval Integration Policy",
        content="# Retrieval Integration Policy",
        source_path="test/retrieval-integration.md",
        status=DocumentStatus.ACTIVE,
        category=VendorCategory.CLOUD_SOFTWARE,
        effective_date=date(2026, 1, 1),
    )
    chunks = (
        _chunk(document, "payment", 0, "Payment terms", "Invoices are payable Net 30."),
        _chunk(document, "shipping", 1, "Shipping", "Ground delivery is included."),
        _chunk(
            document,
            "unsupported-fees",
            2,
            "CSP-05 — Unsupported fees",
            "Account-management fees are not payable.",
        ),
    )
    vectors = embedder.embed_documents([chunk.content for chunk in chunks])
    request = RetrievalQuery(
        query="When must payment happen under invoice terms?",
        category=VendorCategory.CLOUD_SOFTWARE,
        metadata_filter={"integration_test": True},
    )

    database.open()
    try:
        with database.connection() as connection:
            with connection.transaction(force_rollback=True):
                repository.upsert(connection, document, chunks, vectors)

                vector_results = VectorSearcher().search(
                    connection,
                    request,
                    vectors[0],
                    candidate_limit=5,
                )
                lexical_results = KeywordSearcher().search(
                    connection,
                    request,
                    candidate_limit=5,
                )

                assert vector_results[0].chunk.chunk_id.endswith(":payment")
                assert vector_results[0].vector_score == pytest.approx(1.0, abs=1e-6)
                assert lexical_results[0].chunk.chunk_id.endswith(":payment")
                assert lexical_results[0].keyword_score is not None

                clause_results = KeywordSearcher().search(
                    connection,
                    RetrievalQuery(
                        query="Explain CSP-05.",
                        category=VendorCategory.CLOUD_SOFTWARE,
                        metadata_filter={"integration_test": True},
                    ),
                    candidate_limit=5,
                )
                assert clause_results[0].chunk.chunk_id.endswith(":unsupported-fees")
    finally:
        database.close()


def test_as_of_date_selects_only_applicable_expired_terms() -> None:
    database = Database.from_settings(AppSettings.from_environment())
    repository = DocumentRepository()
    embedder = DeterministicEmbeddingClient(dimensions=1024)
    document = SourceDocument(
        document_id="POL-RETRIEVAL-HISTORICAL",
        document_type=DocumentType.SPENDING_POLICY,
        title="Historical Retrieval Policy",
        content="# Historical Retrieval Policy",
        source_path="test/historical-retrieval.md",
        status=DocumentStatus.EXPIRED,
        category=VendorCategory.PROFESSIONAL_SERVICES,
        effective_date=date(2025, 4, 1),
        expiration_date=date(2025, 9, 30),
    )
    chunk = _chunk(
        document,
        "archive-zephyr",
        0,
        "Archive Zephyr",
        "ArchiveZephyr invoices required written milestone acceptance.",
    )
    vector = embedder.embed_documents([chunk.content])[0]

    database.open()
    try:
        with database.connection() as connection:
            with connection.transaction(force_rollback=True):
                repository.upsert(connection, document, (chunk,), (vector,))
                current = RetrievalQuery(
                    query="ArchiveZephyr milestone acceptance",
                    metadata_filter={"integration_test": True},
                )
                applicable = RetrievalQuery(
                    query="ArchiveZephyr milestone acceptance",
                    as_of_date=date(2025, 9, 30),
                    metadata_filter={"integration_test": True},
                )
                after_expiration = RetrievalQuery(
                    query="ArchiveZephyr milestone acceptance",
                    as_of_date=date(2025, 10, 1),
                    metadata_filter={"integration_test": True},
                )

                assert KeywordSearcher().search(
                    connection, current, candidate_limit=5
                ) == ()
                assert VectorSearcher().search(
                    connection, current, vector, candidate_limit=5
                ) == ()
                assert KeywordSearcher().search(
                    connection, applicable, candidate_limit=5
                )[0].chunk.chunk_id == chunk.chunk_id
                assert VectorSearcher().search(
                    connection, applicable, vector, candidate_limit=5
                )[0].chunk.chunk_id == chunk.chunk_id
                assert KeywordSearcher().search(
                    connection, after_expiration, candidate_limit=5
                ) == ()
                assert VectorSearcher().search(
                    connection, after_expiration, vector, candidate_limit=5
                ) == ()
    finally:
        database.close()


def _chunk(
    document: SourceDocument,
    suffix: str,
    ordinal: int,
    section: str,
    content: str,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{document.document_id}:{suffix}",
        document_id=document.document_id,
        document_type=document.document_type,
        section=section,
        ordinal=ordinal,
        content=content,
        source_path=document.source_path,
        status=document.status,
        category=document.category,
        effective_date=document.effective_date,
        expiration_date=document.expiration_date,
        metadata={
            "document_title": document.title,
            "integration_test": True,
        },
    )
