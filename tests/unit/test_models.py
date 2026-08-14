"""Unit tests for data exchanged between RAG and triage stages."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoice_triage.domain import (
    BudgetCheck,
    BudgetStatus,
    DocumentChunk,
    DocumentStatus,
    DocumentType,
    Invoice,
    InvoiceLine,
    MonthlyBudget,
    PaymentTerms,
    RetrievalQuery,
    SearchResult,
    SourceDocument,
    VendorCategory,
)


def make_chunk() -> DocumentChunk:
    """Return a representative chunk with complete retrieval provenance."""

    return DocumentChunk(
        chunk_id="CTR-VND-1001-2026:usage-authorization",
        document_id="CTR-VND-1001-2026",
        document_type=DocumentType.VENDOR_CONTRACT,
        section="Usage authorization",
        ordinal=2,
        content="Monthly usage charges above $750 require authorization.",
        source_path="fixtures/contracts/VND-1001_northstar_cloud.md",
        status=DocumentStatus.ACTIVE,
        vendor_id="VND-1001",
        category=VendorCategory.CLOUD_SOFTWARE,
        effective_date=date(2026, 1, 1),
        expiration_date=date(2026, 12, 31),
        metadata={"heading_level": 2},
    )


def make_invoice_line() -> InvoiceLine:
    """Return a line that preserves exact decimal money values."""

    return InvoiceLine(
        description="Cloud monitoring platform subscription",
        quantity="1",
        unit_price="2400.00",
        amount="2400.00",
    )


def test_contract_requires_vendor_and_category() -> None:
    with pytest.raises(ValidationError, match="requires vendor_id"):
        SourceDocument(
            document_id="CTR-MISSING-VENDOR",
            document_type=DocumentType.VENDOR_CONTRACT,
            title="Incomplete contract",
            content="Contract content",
            source_path="contract.md",
            category=VendorCategory.CLOUD_SOFTWARE,
        )

    with pytest.raises(ValidationError, match="requires category"):
        SourceDocument(
            document_id="CTR-MISSING-CATEGORY",
            document_type=DocumentType.VENDOR_CONTRACT,
            title="Incomplete contract",
            content="Contract content",
            source_path="contract.md",
            vendor_id="VND-1001",
        )


def test_document_rejects_reversed_lifecycle_dates() -> None:
    with pytest.raises(ValidationError, match="expiration_date cannot precede"):
        SourceDocument(
            document_id="CTR-BAD-DATES",
            document_type=DocumentType.VENDOR_CONTRACT,
            title="Contract with bad dates",
            content="Contract content",
            source_path="contract.md",
            vendor_id="VND-1001",
            category=VendorCategory.CLOUD_SOFTWARE,
            effective_date=date(2026, 12, 31),
            expiration_date=date(2026, 1, 1),
        )


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RetrievalQuery(query="Find the payment terms", invented_field=True)


def test_chunk_retains_serializable_provenance() -> None:
    chunk = make_chunk()

    payload = chunk.model_dump(mode="json")

    assert payload["document_id"] == "CTR-VND-1001-2026"
    assert payload["document_type"] == "vendor_contract"
    assert payload["category"] == "cloud_software"
    assert payload["effective_date"] == "2026-01-01"
    assert payload["metadata"] == {"heading_level": 2}


def test_invoice_uses_decimal_money_and_complete_service_period() -> None:
    invoice = Invoice(
        invoice_id="INV-2026-0001",
        vendor_invoice_number="NCS-2026-07-01",
        vendor_id="VND-1001",
        invoice_date=date(2026, 7, 1),
        currency="USD",
        total_due="2400.00",
        payment_terms=PaymentTerms.NET_30,
        cost_center="TECH-OPS",
        service_period_start=date(2026, 6, 1),
        service_period_end=date(2026, 6, 30),
        lines=(make_invoice_line(),),
    )

    assert invoice.total_due == Decimal("2400.00")
    assert invoice.lines[0].unit_price == Decimal("2400.00")


def test_invoice_requires_both_service_period_dates() -> None:
    with pytest.raises(ValidationError, match="must be provided together"):
        Invoice(
            invoice_id="INV-2026-0001",
            vendor_invoice_number="NCS-2026-07-01",
            vendor_id="VND-1001",
            invoice_date=date(2026, 7, 1),
            currency="USD",
            total_due="2400.00",
            lines=(make_invoice_line(),),
            service_period_start=date(2026, 6, 1),
        )


def test_invoice_rejects_empty_lines() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        Invoice(
            invoice_id="INV-EMPTY",
            vendor_invoice_number="EMPTY-1",
            vendor_id="VND-1001",
            invoice_date=date(2026, 7, 1),
            currency="USD",
            total_due="0.00",
            lines=(),
        )


def test_monthly_budget_requires_first_of_month_and_valid_commitment() -> None:
    with pytest.raises(ValidationError, match="first day"):
        MonthlyBudget(
            budget_period=date(2026, 7, 2),
            category=VendorCategory.FACILITIES_MAINTENANCE,
            cost_center="FACILITIES",
            budget_amount="100.00",
            committed_amount="50.00",
            currency="USD",
            owner="Facilities Director",
        )

    with pytest.raises(ValidationError, match="cannot exceed"):
        MonthlyBudget(
            budget_period=date(2026, 7, 1),
            category=VendorCategory.FACILITIES_MAINTENANCE,
            cost_center="FACILITIES",
            budget_amount="100.00",
            committed_amount="101.00",
            currency="USD",
            owner="Facilities Director",
        )


def test_retrieval_query_strips_text_and_bounds_top_k() -> None:
    query = RetrievalQuery(query="  Find the payment terms  ", top_k=10)
    assert query.query == "Find the payment terms"

    with pytest.raises(ValidationError):
        RetrievalQuery(query="Find the payment terms", top_k=0)


def test_search_result_prefers_reranker_score() -> None:
    without_reranker = SearchResult(
        chunk=make_chunk(),
        rank=1,
        vector_score=0.72,
        keyword_score=3.4,
        combined_score=0.81,
    )
    with_reranker = without_reranker.model_copy(
        update={"reranker_score": 0.93}
    )

    assert without_reranker.final_score == 0.81
    assert with_reranker.final_score == 0.93


@pytest.mark.parametrize(
    ("invoice_cost_center", "invoice_amount", "expected_status"),
    [
        ("FACILITIES", "1450.00", BudgetStatus.BUDGET_EXCEEDED),
        ("MARKETING", "100.00", BudgetStatus.COST_CENTER_MISMATCH),
        ("FACILITIES", "1000.00", BudgetStatus.WITHIN_BUDGET),
    ],
)
def test_budget_check_derives_status(
    invoice_cost_center: str,
    invoice_amount: str,
    expected_status: BudgetStatus,
) -> None:
    check = BudgetCheck(
        budget_period="2026-07",
        category=VendorCategory.FACILITIES_MAINTENANCE,
        expected_cost_center="FACILITIES",
        invoice_cost_center=invoice_cost_center,
        currency="USD",
        budget_amount="12500.00",
        committed_amount="11400.00",
        invoice_amount=invoice_amount,
    )

    assert check.status is expected_status
    assert check.projected_spend == Decimal("11400.00") + Decimal(invoice_amount)
    assert check.remaining_after == Decimal("12500.00") - check.projected_spend
