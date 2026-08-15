"""Read-only MCP adapters for authoritative operational data."""

from __future__ import annotations

from datetime import date
import re

from pydantic import BaseModel, ConfigDict, Field

from invoice_triage.domain import (
    BudgetCheck,
    InvoiceIdentifier,
    PersistedInvoice,
    Vendor,
)
from invoice_triage.mcp_server.models import (
    BudgetCheckStatus,
    BudgetEvaluation,
    BudgetSnapshot,
    CheckBudgetResponse,
    DuplicateCheckStatus,
    DuplicateFindingStatus,
    DuplicateInvoiceMatch,
    FlagDuplicateResponse,
    InvoiceIdentifierSummary,
    InvoiceRecordSummary,
    LookupVendorResponse,
    VendorLookupStatus,
    VendorMatch,
    VendorMatchType,
    VendorSummary,
)
from invoice_triage.storage import (
    BudgetRepository,
    Database,
    InvoiceRepository,
    VendorRepository,
)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _LookupVendorRequest(_Request):
    identifier: str = Field(min_length=1, max_length=200)


class _InvoiceIdRequest(_Request):
    invoice_id: str = Field(min_length=1, max_length=100)


class StructuredDataTools:
    """Resolve operational facts without model inference or side effects."""

    def __init__(
        self,
        database: Database,
        *,
        vendor_repository: VendorRepository | None = None,
        budget_repository: BudgetRepository | None = None,
        invoice_repository: InvoiceRepository | None = None,
    ) -> None:
        self._database = database
        self._vendors = vendor_repository or VendorRepository()
        self._budgets = budget_repository or BudgetRepository()
        self._invoices = invoice_repository or InvoiceRepository()

    def lookup_vendor(self, identifier: str) -> LookupVendorResponse:
        request = _LookupVendorRequest(identifier=identifier)
        with self._database.connection() as connection:
            exact = self._vendors.get_by_id(connection, request.identifier)
            if exact is not None:
                matches = (
                    VendorMatch(
                        match_type=VendorMatchType.VENDOR_ID,
                        vendor=_vendor_summary(exact),
                    ),
                )
            else:
                matches = tuple(
                    VendorMatch(
                        match_type=VendorMatchType.NAME_OR_ALIAS,
                        vendor=_vendor_summary(vendor),
                    )
                    for vendor in self._vendors.find_by_name_or_alias(
                        connection,
                        request.identifier,
                    )
                )

        status = (
            VendorLookupStatus.NOT_FOUND
            if not matches
            else VendorLookupStatus.FOUND
            if len(matches) == 1
            else VendorLookupStatus.AMBIGUOUS
        )
        return LookupVendorResponse(
            identifier=request.identifier,
            lookup_status=status,
            result_count=len(matches),
            results=matches,
        )

    def check_budget(
        self,
        invoice_id: str,
    ) -> CheckBudgetResponse:
        request = _InvoiceIdRequest(invoice_id=invoice_id)

        with self._database.connection() as connection:
            invoice = self._invoices.get_by_id(connection, request.invoice_id)
            if invoice is None:
                return CheckBudgetResponse(
                    invoice_id=request.invoice_id,
                    check_status=BudgetCheckStatus.INVOICE_NOT_FOUND,
                )
            period = invoice.invoice_date.strftime("%Y-%m")
            period_date = _budget_period_date(period)
            vendor = self._vendors.get_by_id(connection, invoice.vendor_id)
            if vendor is None:
                return _budget_response(
                    invoice,
                    status=BudgetCheckStatus.VENDOR_NOT_FOUND,
                )
            budget = self._budgets.get(
                connection,
                budget_period=period_date,
                category=vendor.category.value,
                cost_center=vendor.default_cost_center,
            )
            persisted_committed = self._invoices.sum_committed_for_budget(
                connection,
                budget_period=period_date,
                category=vendor.category.value,
                cost_center=vendor.default_cost_center,
                currency=invoice.currency,
                exclude_invoice_id=invoice.invoice_id,
            )

        vendor_summary = _vendor_summary(vendor)
        if budget is None:
            return _budget_response(
                invoice,
                status=BudgetCheckStatus.BUDGET_NOT_FOUND,
                vendor=vendor_summary,
            )

        committed_amount = budget.committed_amount + persisted_committed
        snapshot = BudgetSnapshot(
            budget_period=period,
            category=budget.category,
            cost_center=budget.cost_center,
            budget_amount=budget.budget_amount,
            base_committed_amount=budget.committed_amount,
            persisted_committed_amount=persisted_committed,
            committed_amount=committed_amount,
            currency=budget.currency,
            owner=budget.owner,
        )
        if invoice.currency != vendor.currency or invoice.currency != budget.currency:
            return _budget_response(
                invoice,
                status=BudgetCheckStatus.CURRENCY_MISMATCH,
                vendor=vendor_summary,
                budget=snapshot,
            )

        check = BudgetCheck(
            budget_period=period,
            category=vendor.category,
            expected_cost_center=vendor.default_cost_center,
            invoice_cost_center=invoice.cost_center,
            currency=invoice.currency,
            budget_amount=budget.budget_amount,
            committed_amount=committed_amount,
            invoice_amount=invoice.total_due,
        )
        return _budget_response(
            invoice,
            status=BudgetCheckStatus.EVALUATED,
            vendor=vendor_summary,
            budget=snapshot,
            evaluation=BudgetEvaluation(
                status=check.status,
                expected_cost_center=check.expected_cost_center,
                invoice_cost_center=check.invoice_cost_center,
                invoice_amount=check.invoice_amount,
                projected_spend=check.projected_spend,
                remaining_after=check.remaining_after,
            ),
        )

    def flag_duplicate(self, invoice_id: str) -> FlagDuplicateResponse:
        request = _InvoiceIdRequest(invoice_id=invoice_id)
        with self._database.connection() as connection:
            candidate = self._invoices.get_by_id(connection, request.invoice_id)
            if candidate is None:
                return FlagDuplicateResponse(
                    invoice_id=request.invoice_id,
                    check_status=DuplicateCheckStatus.INVOICE_NOT_FOUND,
                    match_count=0,
                    matches=(),
                )
            matches = self._invoices.find_duplicate_matches(connection, candidate)

        public_matches = tuple(
            DuplicateInvoiceMatch(
                invoice=_invoice_summary(match.invoice),
                reasons=match.reasons,
                matched_identifiers=tuple(
                    _identifier_summary(identifier)
                    for identifier in match.matched_identifiers
                ),
            )
            for match in matches
        )
        return FlagDuplicateResponse(
            invoice_id=request.invoice_id,
            check_status=DuplicateCheckStatus.EVALUATED,
            finding_status=(
                DuplicateFindingStatus.POSSIBLE_DUPLICATE
                if public_matches
                else DuplicateFindingStatus.NO_DUPLICATE
            ),
            candidate=_invoice_summary(candidate),
            match_count=len(public_matches),
            matches=public_matches,
        )


def _budget_response(
    invoice: PersistedInvoice,
    *,
    status: BudgetCheckStatus,
    vendor: VendorSummary | None = None,
    budget: BudgetSnapshot | None = None,
    evaluation: BudgetEvaluation | None = None,
) -> CheckBudgetResponse:
    return CheckBudgetResponse(
        invoice_id=invoice.invoice_id,
        check_status=status,
        vendor=vendor,
        budget=budget,
        evaluation=evaluation,
    )


def _vendor_summary(vendor: Vendor) -> VendorSummary:
    return VendorSummary(
        vendor_id=vendor.vendor_id,
        legal_name=vendor.legal_name,
        display_name=vendor.display_name,
        aliases=vendor.aliases,
        status=vendor.status,
        category=vendor.category,
        historical_spend_12m=vendor.historical_spend_12m,
        currency=vendor.currency,
        default_payment_terms=vendor.default_payment_terms,
        default_cost_center=vendor.default_cost_center,
        contract_file=vendor.contract_file,
    )


def _identifier_summary(identifier: InvoiceIdentifier) -> InvoiceIdentifierSummary:
    return InvoiceIdentifierSummary(
        identifier_type=identifier.identifier_type,
        value=identifier.value,
    )


def _invoice_summary(invoice: PersistedInvoice) -> InvoiceRecordSummary:
    return InvoiceRecordSummary(
        invoice_id=invoice.invoice_id,
        vendor_invoice_number=invoice.vendor_invoice_number,
        vendor_id=invoice.vendor_id,
        invoice_date=invoice.invoice_date,
        received_at=invoice.received_at,
        currency=invoice.currency,
        total_due=invoice.total_due,
        cost_center=invoice.cost_center,
        record_status=invoice.record_status,
        service_period_start=invoice.service_period_start,
        service_period_end=invoice.service_period_end,
        identifiers=tuple(
            _identifier_summary(identifier) for identifier in invoice.identifiers
        ),
        source_path=invoice.source_path,
    )


def _budget_period_date(period: str) -> date:
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period) is None:
        raise ValueError("budget_period must use YYYY-MM")
    return date.fromisoformat(f"{period}-01")
