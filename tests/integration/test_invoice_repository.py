"""PostgreSQL checks for invoice persistence and duplicate signals."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path

import pytest

from invoice_triage.config import AppSettings
from invoice_triage.domain import DuplicateReason, VendorCategory
from invoice_triage.ingestion import load_invoice_fixtures, load_structured_fixtures
from invoice_triage.storage import Database, InvoiceRepository


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("INVOICE_TRIAGE_RUN_INTEGRATION") != "1",
        reason="set INVOICE_TRIAGE_RUN_INTEGRATION=1 to use PostgreSQL",
    ),
]

FIXTURES = Path(__file__).parents[2] / "fixtures"


@pytest.fixture(scope="module")
def database() -> Database:
    db = Database.from_settings(AppSettings.from_environment())
    db.open()
    load_structured_fixtures(
        db,
        vendors_path=FIXTURES / "vendors/vendors.csv",
        budgets_path=FIXTURES / "budgets/monthly_budgets.csv",
    )
    try:
        yield db
    finally:
        db.close()


def test_invoice_load_is_idempotent(database: Database) -> None:
    first = load_invoice_fixtures(database, fixtures_root=FIXTURES)
    second = load_invoice_fixtures(database, fixtures_root=FIXTURES)

    with database.connection() as connection:
        count = InvoiceRepository().count(connection)
        identifier_count = connection.execute(
            "SELECT count(*) AS count FROM invoice_identifiers"
        ).fetchone()

    assert first == second
    assert first.invoices_upserted == 20
    assert count == 20
    assert identifier_count == {"count": first.identifiers_upserted}


def test_repository_finds_exact_and_shipment_duplicates(database: Database) -> None:
    repository = InvoiceRepository()
    with database.connection() as connection:
        invoice_number_candidate = repository.get_by_id(
            connection, "INV-2026-0013"
        )
        shipment_candidate = repository.get_by_id(connection, "INV-2026-0015")
        assert invoice_number_candidate is not None
        assert shipment_candidate is not None
        invoice_number_matches = repository.find_duplicate_matches(
            connection, invoice_number_candidate
        )
        shipment_matches = repository.find_duplicate_matches(
            connection, shipment_candidate
        )

    assert invoice_number_matches[0].invoice.invoice_id == "INV-2026-0001"
    assert DuplicateReason.VENDOR_INVOICE_NUMBER in invoice_number_matches[0].reasons
    assert shipment_matches[0].invoice.invoice_id == "INV-2026-0009"
    assert DuplicateReason.SHIPMENT_IDENTIFIER in shipment_matches[0].reasons
    assert {item.value for item in shipment_matches[0].matched_identifiers} == {
        "BOL-GL-77109",
        "POD-GL-77109",
    }


def test_repository_sums_only_committed_budget_spend(database: Database) -> None:
    with database.connection() as connection:
        committed = InvoiceRepository().sum_committed_for_budget(
            connection,
            budget_period=date(2026, 7, 1),
            category=VendorCategory.FACILITIES_MAINTENANCE.value,
            cost_center="FACILITIES",
            currency="USD",
            exclude_invoice_id="INV-2026-0019",
        )

    assert committed == Decimal("6400.00")
