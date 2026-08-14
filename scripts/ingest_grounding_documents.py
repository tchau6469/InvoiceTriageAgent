"""Parse, chunk, embed, and load contract/policy Markdown into PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path

from invoice_triage.config import AppSettings
from invoice_triage.embeddings import Qwen3EmbeddingClient
from invoice_triage.ingestion import ingest_grounding_documents
from invoice_triage.storage import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=Path("fixtures"),
        help="fixture root containing contracts/ and policies/",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = AppSettings.from_environment()
    client = Qwen3EmbeddingClient(
        model_id=settings.embedding_model_id,
        dimensions=settings.embedding_dimensions,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )
    with Database.from_settings(settings) as database:
        result = ingest_grounding_documents(
            database,
            client,
            fixtures_root=args.fixtures_root,
            source_root=Path.cwd(),
        )
    print(
        f"Ingested {result.documents_written} documents and "
        f"{result.chunks_written} chunks with {result.embedding_model_id} "
        f"({result.embedding_dimensions} dimensions)."
    )


if __name__ == "__main__":
    main()
