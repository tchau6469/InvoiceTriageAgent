"""Shared conversion from PostgreSQL retrieval rows to domain objects."""

from __future__ import annotations

from typing import Any

from invoice_triage.domain import DocumentChunk


CHUNK_SELECT_COLUMNS = """
    chunk_id,
    document_id,
    document_type,
    section,
    ordinal,
    content,
    source_path,
    status,
    vendor_id,
    category,
    effective_date,
    expiration_date,
    metadata
"""


def chunk_from_row(row: dict[str, Any]) -> DocumentChunk:
    """Restore a retrieval chunk with all explanation provenance."""

    return DocumentChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        document_type=row["document_type"],
        section=row["section"],
        ordinal=row["ordinal"],
        content=row["content"],
        source_path=row["source_path"],
        status=row["status"],
        vendor_id=row["vendor_id"],
        category=row["category"],
        effective_date=row["effective_date"],
        expiration_date=row["expiration_date"],
        metadata=row["metadata"],
    )
