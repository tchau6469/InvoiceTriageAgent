"""Tests for deterministic vendor, budget, and duplicate MCP adapters."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from pydantic import ValidationError

from invoice_triage.domain import (
    BudgetStatus,
    DuplicateReason,
    InvoiceDuplicateMatch,
    InvoiceIdentifier,
    InvoiceIdentifierType,
    InvoiceRecordStatus,
    MonthlyBudget,
    PaymentTerms,
    PersistedInvoice,
    Vendor,
    VendorCategory,
    VendorContact,
    VendorStatus,
)
from invoice_triage.mcp_server import (
    BudgetCheckStatus,
    DuplicateCheckStatus,
    DuplicateFindingStatus,
    StructuredDataTools,
    VendorLookupStatus,
    VendorMatchType,
)


def test_lookup_vendor_prefers_exact_id_and_allowlists_output() -> None:
    vendor = _vendor()
    vendors = StaticVendorRepository(by_id={vendor.vendor_id: vendor})

    response = _tool(vendors=vendors).lookup_vendor("  VND-1007  ")

    assert response.lookup_status is VendorLookupStatus.FOUND
    assert response.result_count == 1
    assert response.results[0].match_type is VendorMatchType.VENDOR_ID
    assert response.results[0].vendor.status is VendorStatus.ACTIVE
    assert vendors.name_queries == []
    payload = response.model_dump(mode="json")["results"][0]["vendor"]
    assert "contact" not in payload
    assert "remittance_profile_ref" not in payload


def test_lookup_vendor_reports_ambiguous_name_or_alias() -> None:
    vendors = StaticVendorRepository(
        by_name=(_vendor(), _vendor(vendor_id="VND-2007")),
    )
    response = _tool(vendors=vendors).lookup_vendor("Clearwater")

    assert response.lookup_status is VendorLookupStatus.AMBIGUOUS
    assert response.result_count == 2
    assert all(
        result.match_type is VendorMatchType.NAME_OR_ALIAS
        for result in response.results
    )


def test_lookup_vendor_returns_not_found_without_guessing() -> None:
    response = _tool().lookup_vendor("Unknown Supplier")

    assert response.lookup_status is VendorLookupStatus.NOT_FOUND
    assert response.results == ()


@pytest.mark.parametrize(
    ("cost_center", "amount", "expected"),
    [
        ("FACILITIES", "1000.00", BudgetStatus.WITHIN_BUDGET),
        ("FACILITIES", "1500.00", BudgetStatus.BUDGET_EXCEEDED),
        ("MARKETING", "100.00", BudgetStatus.COST_CENTER_MISMATCH),
    ],
)
def test_check_budget_derives_all_scope_and_adds_committed_invoices(
    cost_center: str,
    amount: str,
    expected: BudgetStatus,
) -> None:
    invoice = _invoice(cost_center=cost_center, total_due=amount)
    vendors = StaticVendorRepository(by_id={invoice.vendor_id: _vendor()})
    budgets = StaticBudgetRepository(_budget())
    invoices = StaticInvoiceRepository(
        by_id={invoice.invoice_id: invoice},
        committed=Decimal("6400.00"),
    )

    response = _tool(
        vendors=vendors,
        budgets=budgets,
        invoices=invoices,
    ).check_budget(invoice.invoice_id)

    assert response.check_status is BudgetCheckStatus.EVALUATED
    assert response.budget is not None
    assert response.budget.base_committed_amount == Decimal("5000.00")
    assert response.budget.persisted_committed_amount == Decimal("6400.00")
    assert response.budget.committed_amount == Decimal("11400.00")
    assert response.evaluation is not None
    assert response.evaluation.status is expected
    assert response.evaluation.projected_spend == Decimal("11400.00") + Decimal(
        amount
    )
    assert invoices.last_budget_key == (
        date(2026, 7, 1),
        "facilities_maintenance",
        "FACILITIES",
        "USD",
        invoice.invoice_id,
    )


def test_check_budget_separates_missing_prerequisites_and_currency_mismatch() -> None:
    invoice = _invoice()
    missing_invoice = _tool().check_budget("INV-404")
    missing_vendor = _tool(
        invoices=StaticInvoiceRepository(by_id={invoice.invoice_id: invoice}),
    ).check_budget(invoice.invoice_id)
    missing_budget = _tool(
        vendors=StaticVendorRepository(by_id={invoice.vendor_id: _vendor()}),
        invoices=StaticInvoiceRepository(by_id={invoice.invoice_id: invoice}),
    ).check_budget(invoice.invoice_id)
    eur_invoice = invoice.model_copy(update={"currency": "EUR"})
    currency_mismatch = _tool(
        vendors=StaticVendorRepository(by_id={invoice.vendor_id: _vendor()}),
        budgets=StaticBudgetRepository(_budget()),
        invoices=StaticInvoiceRepository(by_id={invoice.invoice_id: eur_invoice}),
    ).check_budget(invoice.invoice_id)

    assert missing_invoice.check_status is BudgetCheckStatus.INVOICE_NOT_FOUND
    assert missing_vendor.check_status is BudgetCheckStatus.VENDOR_NOT_FOUND
    assert missing_budget.check_status is BudgetCheckStatus.BUDGET_NOT_FOUND
    assert currency_mismatch.check_status is BudgetCheckStatus.CURRENCY_MISMATCH
    assert currency_mismatch.evaluation is None


def test_flag_duplicate_maps_all_signals_and_exact_matches() -> None:
    candidate = _invoice(
        invoice_id="INV-NEW",
        vendor_invoice_number="CFG-HQ-2026-07",
        identifiers=(
            InvoiceIdentifier(
                identifier_type=InvoiceIdentifierType.BILL_OF_LADING,
                value="BOL-77",
            ),
        ),
    )
    earlier = _invoice(invoice_id="INV-EARLIER")
    match = InvoiceDuplicateMatch(
        invoice=earlier,
        reasons=(
            DuplicateReason.VENDOR_INVOICE_NUMBER,
            DuplicateReason.SERVICE_PERIOD_AMOUNT,
            DuplicateReason.SHIPMENT_IDENTIFIER,
        ),
        matched_identifiers=(candidate.identifiers[0],),
    )
    invoices = StaticInvoiceRepository(
        by_id={candidate.invoice_id: candidate},
        matches=(match,),
    )

    response = _tool(invoices=invoices).flag_duplicate(candidate.invoice_id)

    assert response.check_status is DuplicateCheckStatus.EVALUATED
    assert response.finding_status is DuplicateFindingStatus.POSSIBLE_DUPLICATE
    assert response.match_count == 1
    assert response.matches[0].invoice.invoice_id == "INV-EARLIER"
    assert response.matches[0].reasons == match.reasons
    assert response.matches[0].matched_identifiers[0].value == "BOL-77"


def test_flag_duplicate_distinguishes_no_match_and_missing_invoice() -> None:
    invoice = _invoice()
    no_match = _tool(
        invoices=StaticInvoiceRepository(by_id={invoice.invoice_id: invoice}),
    ).flag_duplicate(invoice.invoice_id)
    missing = _tool().flag_duplicate("INV-404")

    assert no_match.finding_status is DuplicateFindingStatus.NO_DUPLICATE
    assert no_match.matches == ()
    assert missing.check_status is DuplicateCheckStatus.INVOICE_NOT_FOUND
    assert missing.finding_status is None


@pytest.mark.parametrize("invoice_id", ["", "   "])
def test_invoice_tools_reject_empty_ids(invoice_id: str) -> None:
    with pytest.raises(ValidationError):
        _tool().check_budget(invoice_id)
    with pytest.raises(ValidationError):
        _tool().flag_duplicate(invoice_id)


class StaticDatabase:
    @contextmanager
    def connection(self) -> Iterator[object]:
        yield object()


class StaticVendorRepository:
    def __init__(
        self,
        *,
        by_id: dict[str, Vendor] | None = None,
        by_name: tuple[Vendor, ...] = (),
    ) -> None:
        self.by_id = by_id or {}
        self.by_name = by_name
        self.name_queries: list[str] = []

    def get_by_id(self, _connection: object, vendor_id: str) -> Vendor | None:
        return self.by_id.get(vendor_id)

    def find_by_name_or_alias(
        self,
        _connection: object,
        name: str,
    ) -> tuple[Vendor, ...]:
        self.name_queries.append(name)
        return self.by_name


class StaticBudgetRepository:
    def __init__(self, budget: MonthlyBudget | None = None) -> None:
        self.budget = budget

    def get(
        self,
        _connection: object,
        *,
        budget_period: date,
        category: str,
        cost_center: str,
    ) -> MonthlyBudget | None:
        return self.budget


class StaticInvoiceRepository:
    def __init__(
        self,
        *,
        by_id: dict[str, PersistedInvoice] | None = None,
        committed: Decimal = Decimal("0"),
        matches: tuple[InvoiceDuplicateMatch, ...] = (),
    ) -> None:
        self.by_id = by_id or {}
        self.committed = committed
        self.matches = matches
        self.last_budget_key: tuple[date, str, str, str, str | None] | None = None

    def get_by_id(
        self,
        _connection: object,
        invoice_id: str,
    ) -> PersistedInvoice | None:
        return self.by_id.get(invoice_id)

    def sum_committed_for_budget(
        self,
        _connection: object,
        *,
        budget_period: date,
        category: str,
        cost_center: str,
        currency: str,
        exclude_invoice_id: str | None = None,
    ) -> Decimal:
        self.last_budget_key = (
            budget_period,
            category,
            cost_center,
            currency,
            exclude_invoice_id,
        )
        return self.committed

    def find_duplicate_matches(
        self,
        _connection: object,
        _candidate: PersistedInvoice,
    ) -> tuple[InvoiceDuplicateMatch, ...]:
        return self.matches


def _tool(
    *,
    vendors: StaticVendorRepository | None = None,
    budgets: StaticBudgetRepository | None = None,
    invoices: StaticInvoiceRepository | None = None,
) -> StructuredDataTools:
    return StructuredDataTools(
        StaticDatabase(),  # type: ignore[arg-type]
        vendor_repository=vendors or StaticVendorRepository(),  # type: ignore[arg-type]
        budget_repository=budgets or StaticBudgetRepository(),  # type: ignore[arg-type]
        invoice_repository=invoices or StaticInvoiceRepository(),  # type: ignore[arg-type]
    )


def _vendor(*, vendor_id: str = "VND-1007") -> Vendor:
    return Vendor(
        vendor_id=vendor_id,
        legal_name="Clearwater Facilities Group Inc.",
        display_name="Clearwater Facilities",
        aliases=("Clearwater Facilities", "CFG Services"),
        status=VendorStatus.ACTIVE,
        category=VendorCategory.FACILITIES_MAINTENANCE,
        historical_spend_12m="70200.00",
        currency="USD",
        default_payment_terms=PaymentTerms.NET_30,
        default_cost_center="FACILITIES",
        contact=VendorContact(
            name="Synthetic Contact",
            title="Accounts Receivable",
            email="ar@clearwater.example",
            phone="312-555-0107",
        ),
        contract_file="contracts/VND-1007_clearwater_facilities.md",
        remittance_profile_ref="vendor-remittance/VND-1007",
    )


def _budget() -> MonthlyBudget:
    return MonthlyBudget(
        budget_period=date(2026, 7, 1),
        category=VendorCategory.FACILITIES_MAINTENANCE,
        cost_center="FACILITIES",
        budget_amount="12500.00",
        committed_amount="5000.00",
        currency="USD",
        owner="Facilities Director",
    )


def _invoice(
    *,
    invoice_id: str = "INV-2026-0019",
    vendor_invoice_number: str = "CFG-EM-2026-119",
    cost_center: str = "FACILITIES",
    total_due: str = "1450.00",
    identifiers: tuple[InvoiceIdentifier, ...] = (),
) -> PersistedInvoice:
    return PersistedInvoice(
        invoice_id=invoice_id,
        vendor_invoice_number=vendor_invoice_number,
        vendor_id="VND-1007",
        invoice_date=date(2026, 7, 24),
        received_at=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
        currency="USD",
        total_due=total_due,
        cost_center=cost_center,
        record_status=InvoiceRecordStatus.PENDING_REVIEW,
        service_period_start=date(2026, 7, 1),
        service_period_end=date(2026, 7, 31),
        identifiers=identifiers,
        source_path=f"fixtures/invoices/{invoice_id}.md",
        content_hash="0" * 64,
    )
