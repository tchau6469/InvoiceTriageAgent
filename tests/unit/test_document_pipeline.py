"""Corpus boundary tests that prevent evaluation leakage."""

from pathlib import Path

from invoice_triage.ingestion import (
    discover_grounding_sources,
    prepare_grounding_documents,
)


PROJECT_ROOT = Path(__file__).parents[2]
FIXTURES_ROOT = PROJECT_ROOT / "fixtures"


def test_discovery_includes_only_contracts_and_policies() -> None:
    sources = discover_grounding_sources(FIXTURES_ROOT)

    assert len(sources) == 24
    assert sum("/contracts/" in path.as_posix() for path in sources) == 18
    assert sum("/policies/" in path.as_posix() for path in sources) == 6
    assert all("/invoices/" not in path.as_posix() for path in sources)
    assert all("/evaluation/" not in path.as_posix() for path in sources)


def test_complete_corpus_prepares_stable_unique_chunks() -> None:
    prepared = prepare_grounding_documents(FIXTURES_ROOT, source_root=PROJECT_ROOT)
    chunks = [chunk for _, document_chunks in prepared for chunk in document_chunks]

    assert len(prepared) == 24
    assert len(chunks) == 195
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all(chunk.metadata["source_format"] == "markdown" for chunk in chunks)
