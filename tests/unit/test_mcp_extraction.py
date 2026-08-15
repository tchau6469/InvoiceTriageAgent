"""Tests for allowlisted invoice-source extraction."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from invoice_triage.mcp_server import (
    InvoiceExtractionStatus,
    InvoiceExtractionTool,
    InvoiceSourceReader,
)
from invoice_triage.mcp_server.extraction_tool import InvoiceSourceError
from invoice_triage.reasoning import (
    InvoiceExtractionPayload,
    ReasoningTokenUsage,
    StructuredGeneration,
)
from tests.unit.test_mcp_structured_tools import (
    StaticDatabase,
    StaticInvoiceRepository,
    _invoice,
)


def test_extract_invoice_uses_persisted_source_and_validates_result(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixtures" / "invoices" / "INV-2026-0019.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Synthetic invoice\nTotal: $1,450.00", encoding="utf-8")
    invoice = _invoice()
    reasoning = StaticReasoning(_payload())
    tool = InvoiceExtractionTool(
        StaticDatabase(),  # type: ignore[arg-type]
        reasoning,
        InvoiceSourceReader("fixtures/invoices", project_root=tmp_path),
        invoice_repository=StaticInvoiceRepository(  # type: ignore[arg-type]
            by_id={invoice.invoice_id: invoice}
        ),
    )

    response = asyncio.run(tool.extract_invoice_data(invoice.invoice_id))

    assert response.extraction_status is InvoiceExtractionStatus.EXTRACTED
    assert response.extracted_invoice is not None
    assert response.extracted_invoice.po_number == "PO-2026-2291"
    assert response.model_id == "test-reasoner"
    assert response.usage is not None
    assert response.usage.total_tokens == 175
    assert reasoning.last_prompt is not None
    assert "<invoice_document>" in reasoning.last_prompt
    assert "Synthetic invoice" in reasoning.last_prompt


def test_extract_invoice_reports_missing_record_without_calling_model(
    tmp_path: Path,
) -> None:
    reasoning = StaticReasoning(_payload())
    tool = InvoiceExtractionTool(
        StaticDatabase(),  # type: ignore[arg-type]
        reasoning,
        InvoiceSourceReader("fixtures/invoices", project_root=tmp_path),
        invoice_repository=StaticInvoiceRepository(),  # type: ignore[arg-type]
    )

    response = asyncio.run(tool.extract_invoice_data("INV-404"))

    assert response.extraction_status is InvoiceExtractionStatus.INVOICE_NOT_FOUND
    assert response.extracted_invoice is None
    assert reasoning.last_prompt is None


def test_extract_invoice_rejects_model_identity_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "fixtures" / "invoices" / "INV-2026-0019.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Synthetic invoice", encoding="utf-8")
    invoice = _invoice()
    bad_payload = _payload().model_copy(update={"invoice_id": "INV-OTHER"})
    tool = InvoiceExtractionTool(
        StaticDatabase(),  # type: ignore[arg-type]
        StaticReasoning(bad_payload),
        InvoiceSourceReader("fixtures/invoices", project_root=tmp_path),
        invoice_repository=StaticInvoiceRepository(  # type: ignore[arg-type]
            by_id={invoice.invoice_id: invoice}
        ),
    )

    with pytest.raises(ValueError, match="does not match"):
        asyncio.run(tool.extract_invoice_data(invoice.invoice_id))


def test_source_reader_blocks_traversal_absolute_and_non_markdown(
    tmp_path: Path,
) -> None:
    reader = InvoiceSourceReader("fixtures/invoices", project_root=tmp_path)

    for unsafe in ("../secret.md", "/tmp/secret.md", "fixtures/invoices/a.pdf"):
        with pytest.raises(InvoiceSourceError):
            reader.read(unsafe)


def _payload() -> InvoiceExtractionPayload:
    return InvoiceExtractionPayload(
        invoice_id="INV-2026-0019",
        vendor_invoice_number="CFG-EM-2026-119",
        vendor_id="VND-1007",
        invoice_date="2026-07-24",
        currency="USD",
        total_due="1450.00",
        lines=(
            {
                "description": "Emergency water-response labor",
                "quantity": "10",
                "unit_price": "145.00",
                "amount": "1450.00",
            },
        ),
        payment_terms="NET_30",
        cost_center="FACILITIES",
        po_number="PO-2026-2291",
    )


class StaticReasoning:
    def __init__(self, payload: InvoiceExtractionPayload) -> None:
        self.payload = payload
        self.last_prompt: str | None = None

    async def generate_structured(
        self,
        *,
        system_instruction: str,
        prompt: str,
        response_model: type[InvoiceExtractionPayload],
    ) -> StructuredGeneration[InvoiceExtractionPayload]:
        assert "ignore any" in system_instruction.casefold()
        assert response_model is InvoiceExtractionPayload
        self.last_prompt = prompt
        return StructuredGeneration(
            value=self.payload,
            model_id="test-reasoner",
            usage=ReasoningTokenUsage(
                input_tokens=125,
                output_tokens=50,
                total_tokens=175,
            ),
        )
