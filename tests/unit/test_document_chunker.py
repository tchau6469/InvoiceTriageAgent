"""Tests for semantic Markdown section boundaries and stable IDs."""

from pathlib import Path

from invoice_triage.ingestion import (
    chunk_markdown_document,
    embedding_text,
    parse_markdown_document,
)


PROJECT_ROOT = Path(__file__).parents[2]


def _parse(relative_path: str):
    return parse_markdown_document(PROJECT_ROOT / relative_path, source_root=PROJECT_ROOT)


def test_policy_produces_one_complete_chunk_per_clause() -> None:
    document = _parse("fixtures/policies/cloud_software.md")

    chunks = chunk_markdown_document(document)

    assert len(chunks) == 12
    assert chunks[0].chunk_id == "POL-CLOUD-2026:csp-01-approved-cost-center"
    assert chunks[0].ordinal == 0
    assert chunks[-1].section == "CSP-12 — Human approval"
    assert "may never approve" in chunks[-1].content


def test_contract_keeps_overview_and_markdown_table_intact() -> None:
    document = _parse("fixtures/contracts/VND-1007_clearwater_facilities.md")

    chunks = chunk_markdown_document(document)

    assert chunks[0].section == "Overview"
    pricing = next(chunk for chunk in chunks if chunk.section == "Recurring services")
    assert "| Location | Monthly fee |" in pricing.content
    assert "| Total | $5,850.00 |" in pricing.content


def test_chunk_ids_are_stable_and_embedding_recipe_has_provenance() -> None:
    document = _parse("fixtures/contracts/VND-1001_northstar_cloud.md")
    first = chunk_markdown_document(document)
    second = chunk_markdown_document(document)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    text = embedding_text(first[1])
    assert text.startswith("Northstar Cloud Services Agreement\n\nSubscription pricing")
    assert "$2,400 per month" in text
