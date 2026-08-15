"""Live PostgreSQL checks for MCP vendor and budget adapters."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from invoice_triage.config import AppSettings
from invoice_triage.domain import BudgetStatus, DuplicateReason, VendorStatus
from invoice_triage.ingestion import load_invoice_fixtures, load_structured_fixtures
from invoice_triage.mcp_server import (
    BudgetCheckStatus,
    DuplicateFindingStatus,
    StructuredDataTools,
    VendorLookupStatus,
)
from invoice_triage.storage import Database


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("INVOICE_TRIAGE_RUN_INTEGRATION") != "1",
        reason="set INVOICE_TRIAGE_RUN_INTEGRATION=1 to use PostgreSQL",
    ),
]

FIXTURES = Path(__file__).parents[2] / "fixtures"


@pytest.fixture(scope="module")
def tools() -> StructuredDataTools:
    database = Database.from_settings(AppSettings.from_environment())
    database.open()
    load_structured_fixtures(
        database,
        vendors_path=FIXTURES / "vendors/vendors.csv",
        budgets_path=FIXTURES / "budgets/monthly_budgets.csv",
    )
    load_invoice_fixtures(database, fixtures_root=FIXTURES)
    try:
        yield StructuredDataTools(database)
    finally:
        database.close()


def test_live_vendor_lookup_resolves_alias_and_inactive_status(
    tools: StructuredDataTools,
) -> None:
    response = tools.lookup_vendor("ADM Consulting")

    assert response.lookup_status is VendorLookupStatus.FOUND
    assert response.results[0].vendor.vendor_id == "VND-1010"
    assert response.results[0].vendor.status is VendorStatus.INACTIVE


def test_live_budget_check_derives_cost_center_and_detects_mismatch(
    tools: StructuredDataTools,
) -> None:
    response = tools.check_budget(
        "INV-2026-0018",
    )

    assert response.check_status is BudgetCheckStatus.EVALUATED
    assert response.vendor is not None
    assert response.vendor.default_cost_center == "DATA-PLATFORM"
    assert response.evaluation is not None
    assert response.evaluation.status is BudgetStatus.COST_CENTER_MISMATCH


def test_live_budget_check_detects_projected_overage(
    tools: StructuredDataTools,
) -> None:
    response = tools.check_budget(
        "INV-2026-0019",
    )

    assert response.check_status is BudgetCheckStatus.EVALUATED
    assert response.evaluation is not None
    assert response.evaluation.status is BudgetStatus.BUDGET_EXCEEDED
    assert response.budget is not None
    assert str(response.budget.base_committed_amount) == "5000.00"
    assert str(response.budget.persisted_committed_amount) == "6400.00"
    assert str(response.evaluation.projected_spend) == "12850.00"
    assert str(response.evaluation.remaining_after) == "-350.00"


def test_live_budget_check_reports_missing_invoice_without_fabricating_result(
    tools: StructuredDataTools,
) -> None:
    response = tools.check_budget("INV-404")

    assert response.check_status is BudgetCheckStatus.INVOICE_NOT_FOUND
    assert response.evaluation is None


@pytest.mark.parametrize(
    ("invoice_id", "matched_invoice_id", "reason"),
    [
        (
            "INV-2026-0013",
            "INV-2026-0001",
            DuplicateReason.VENDOR_INVOICE_NUMBER,
        ),
        (
            "INV-2026-0014",
            "INV-2026-0005",
            DuplicateReason.VENDOR_INVOICE_NUMBER,
        ),
        (
            "INV-2026-0015",
            "INV-2026-0009",
            DuplicateReason.SHIPMENT_IDENTIFIER,
        ),
    ],
)
def test_live_duplicate_check_finds_intentional_pairs(
    tools: StructuredDataTools,
    invoice_id: str,
    matched_invoice_id: str,
    reason: DuplicateReason,
) -> None:
    response = tools.flag_duplicate(invoice_id)

    assert response.finding_status is DuplicateFindingStatus.POSSIBLE_DUPLICATE
    assert response.match_count == 1
    assert response.matches[0].invoice.invoice_id == matched_invoice_id
    assert reason in response.matches[0].reasons


def test_live_duplicate_check_does_not_flag_original_against_later_copy(
    tools: StructuredDataTools,
) -> None:
    response = tools.flag_duplicate("INV-2026-0001")

    assert response.finding_status is DuplicateFindingStatus.NO_DUPLICATE
    assert response.matches == ()
