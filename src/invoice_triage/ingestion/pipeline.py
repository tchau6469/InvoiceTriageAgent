"""End-to-end grounding-document ingestion orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from invoice_triage.domain import DocumentChunk, SourceDocument
from invoice_triage.embeddings import EmbeddingClient
from invoice_triage.ingestion.chunker import chunk_markdown_document, embedding_text
from invoice_triage.ingestion.parser import parse_markdown_document
from invoice_triage.storage import Database, DocumentRepository


DATABASE_EMBEDDING_DIMENSIONS = 1024


class DocumentIngestionError(ValueError):
    """The corpus cannot be safely ingested as one validated collection."""


@dataclass(frozen=True)
class DocumentIngestionResult:
    documents_written: int
    chunks_written: int
    embedding_model_id: str
    embedding_dimensions: int


def discover_grounding_sources(fixtures_root: Path) -> tuple[Path, ...]:
    """Return only contracts and policies; invoices/evaluation data are excluded."""

    paths = [
        *fixtures_root.joinpath("contracts").glob("*.md"),
        *fixtures_root.joinpath("policies").glob("*.md"),
    ]
    return tuple(sorted(paths))


def prepare_grounding_documents(
    fixtures_root: Path,
    *,
    source_root: Path,
) -> tuple[tuple[SourceDocument, tuple[DocumentChunk, ...]], ...]:
    """Parse and chunk the complete corpus before any model or database work."""

    sources = discover_grounding_sources(fixtures_root)
    if not sources:
        raise DocumentIngestionError(f"no grounding Markdown found under {fixtures_root}")

    prepared: list[tuple[SourceDocument, tuple[DocumentChunk, ...]]] = []
    document_ids: set[str] = set()
    source_paths: set[str] = set()
    for path in sources:
        document = parse_markdown_document(path, source_root=source_root)
        if document.document_id in document_ids:
            raise DocumentIngestionError(f"duplicate document_id: {document.document_id}")
        if document.source_path in source_paths:
            raise DocumentIngestionError(f"duplicate source_path: {document.source_path}")
        document_ids.add(document.document_id)
        source_paths.add(document.source_path)
        prepared.append((document, chunk_markdown_document(document)))
    return tuple(prepared)


def ingest_grounding_documents(
    database: Database,
    embedding_client: EmbeddingClient,
    *,
    fixtures_root: Path = Path("fixtures"),
    source_root: Path | None = None,
    repository: DocumentRepository | None = None,
) -> DocumentIngestionResult:
    """Validate, embed, and atomically upsert all grounding documents."""

    if embedding_client.dimensions != DATABASE_EMBEDDING_DIMENSIONS:
        raise DocumentIngestionError(
            "the current document_chunks schema requires 1024-dimensional embeddings"
        )
    prepared = prepare_grounding_documents(
        fixtures_root,
        source_root=source_root or Path.cwd(),
    )
    flattened_chunks = [chunk for _, chunks in prepared for chunk in chunks]
    texts = [embedding_text(chunk) for chunk in flattened_chunks]
    embeddings = embedding_client.embed_documents(texts)
    if len(embeddings) != len(flattened_chunks):
        raise DocumentIngestionError("embedding provider did not return one vector per chunk")
    if any(len(vector) != embedding_client.dimensions for vector in embeddings):
        raise DocumentIngestionError("embedding dimensions do not match provider configuration")

    enriched_chunks = [
        chunk.model_copy(
            update={
                "metadata": {
                    **chunk.metadata,
                    "embedding_model_id": embedding_client.model_id,
                    "embedding_dimensions": embedding_client.dimensions,
                    "embedding_text_version": "title-section-content-v1",
                }
            }
        )
        for chunk in flattened_chunks
    ]

    document_repository = repository or DocumentRepository()
    offset = 0
    with database.connection() as connection:
        for document, chunks in prepared:
            count = len(chunks)
            document_repository.upsert(
                connection,
                document,
                enriched_chunks[offset : offset + count],
                embeddings[offset : offset + count],
            )
            offset += count

    return DocumentIngestionResult(
        documents_written=len(prepared),
        chunks_written=len(flattened_chunks),
        embedding_model_id=embedding_client.model_id,
        embedding_dimensions=embedding_client.dimensions,
    )
