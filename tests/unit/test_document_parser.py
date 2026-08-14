"""Tests for strict Markdown/front-matter parsing."""

from pathlib import Path

import pytest

from invoice_triage.domain import DocumentType, VendorCategory
from invoice_triage.ingestion import DocumentParseError, parse_markdown_document


PROJECT_ROOT = Path(__file__).parents[2]


def test_parse_contract_retains_scope_and_portable_source_path() -> None:
    path = PROJECT_ROOT / "fixtures/contracts/VND-1001_northstar_cloud.md"

    document = parse_markdown_document(path, source_root=PROJECT_ROOT)

    assert document.document_id == "CTR-VND-1001-2026"
    assert document.document_type is DocumentType.VENDOR_CONTRACT
    assert document.vendor_id == "VND-1001"
    assert document.category is VendorCategory.CLOUD_SOFTWARE
    assert document.title == "Northstar Cloud Services Agreement"
    assert document.source_path == "fixtures/contracts/VND-1001_northstar_cloud.md"
    assert document.metadata == {"source_format": "markdown"}


def test_parse_rejects_unknown_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "invalid.md"
    path.write_text(
        """---
document_id: POL-TEST
document_type: spending_policy
category: cloud_software
status: active
surprise: unsafe
---
# Test

## Rule

Do the documented thing.
""",
        encoding="utf-8",
    )

    with pytest.raises(DocumentParseError, match="unknown front-matter fields: surprise"):
        parse_markdown_document(path, source_root=tmp_path)


def test_parse_rejects_missing_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "invalid.md"
    path.write_text("# No metadata\n", encoding="utf-8")

    with pytest.raises(DocumentParseError, match="must begin with YAML front matter"):
        parse_markdown_document(path)
