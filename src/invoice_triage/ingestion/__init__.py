"""Document and structured-data ingestion."""

from invoice_triage.ingestion.chunker import (
    DocumentChunkError,
    chunk_markdown_document,
    embedding_text,
)
from invoice_triage.ingestion.parser import DocumentParseError, parse_markdown_document
from invoice_triage.ingestion.pipeline import (
    DocumentIngestionError,
    DocumentIngestionResult,
    discover_grounding_sources,
    ingest_grounding_documents,
    prepare_grounding_documents,
)
from invoice_triage.ingestion.structured import (
    FixtureValidationError,
    StructuredLoadResult,
    load_structured_fixtures,
    read_budget_fixtures,
    read_vendor_fixtures,
)

__all__ = [
    "DocumentChunkError",
    "DocumentIngestionError",
    "DocumentIngestionResult",
    "DocumentParseError",
    "FixtureValidationError",
    "StructuredLoadResult",
    "chunk_markdown_document",
    "discover_grounding_sources",
    "embedding_text",
    "ingest_grounding_documents",
    "load_structured_fixtures",
    "parse_markdown_document",
    "prepare_grounding_documents",
    "read_budget_fixtures",
    "read_vendor_fixtures",
]
