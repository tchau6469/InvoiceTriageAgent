"""Tests for normalizing Markdown invoice fixtures into persisted records."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_triage.domain import InvoiceIdentifierType, InvoiceRecordStatus
from invoice_triage.ingestion import (
    InvoiceFixtureError,
    parse_invoice_record,
    read_invoice_fixtures,
)


FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_fixture_corpus_has_explicit_lifecycle_states() -> None:
    invoices = read_invoice_fixtures(FIXTURES)

    assert len(invoices) == 20
    assert sum(
        invoice.record_status is InvoiceRecordStatus.COMMITTED
        for invoice in invoices
    ) == 12
    assert sum(
        invoice.record_status is InvoiceRecordStatus.PENDING_REVIEW
        for invoice in invoices
    ) == 8


def test_parser_extracts_period_money_and_typed_identifiers() -> None:
    invoice = parse_invoice_record(
        FIXTURES / "invoices/INV-2026-0015.md",
        source_root=FIXTURES.parent,
    )

    assert str(invoice.total_due) == "1275.00"
    assert invoice.service_period_start is None
    assert invoice.service_period_end is None
    assert {identifier.identifier_type for identifier in invoice.identifiers} == {
        InvoiceIdentifierType.BILL_OF_LADING,
        InvoiceIdentifierType.PROOF_OF_DELIVERY,
        InvoiceIdentifierType.PURCHASE_ORDER,
    }
    assert invoice.source_path == "fixtures/invoices/INV-2026-0015.md"
    assert len(invoice.content_hash) == 64


def test_parser_handles_cross_month_service_period() -> None:
    invoice = parse_invoice_record(
        FIXTURES / "invoices/INV-2026-0006.md",
        source_root=FIXTURES.parent,
    )

    assert invoice.service_period_start.isoformat() == "2026-04-01"
    assert invoice.service_period_end.isoformat() == "2026-06-30"


def test_parser_rejects_unknown_front_matter(tmp_path: Path) -> None:
    source = tmp_path / "bad.md"
    source.write_text(
        """---
invoice_id: INV-BAD
vendor_invoice_number: BAD-1
vendor_id: VND-1001
invoice_date: 2026-07-01
currency: USD
record_status: pending_review
received_at: 2026-07-01T12:00:00Z
invented: true
---

Cost center: `TECH-OPS`

**Total due: $10.00**
""",
        encoding="utf-8",
    )

    with pytest.raises(InvoiceFixtureError, match="unknown invoice front-matter"):
        parse_invoice_record(source)


def test_parser_rejects_missing_operational_fields(tmp_path: Path) -> None:
    source = tmp_path / "bad.md"
    source.write_text(
        """---
invoice_id: INV-BAD
vendor_invoice_number: BAD-1
vendor_id: VND-1001
invoice_date: 2026-07-01
currency: USD
record_status: pending_review
received_at: 2026-07-01T12:00:00Z
---

This invoice intentionally omits the cost center and total due.
""",
        encoding="utf-8",
    )

    with pytest.raises(InvoiceFixtureError, match="total due was not found"):
        parse_invoice_record(source)
