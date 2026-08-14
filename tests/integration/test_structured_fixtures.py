"""Live repository and idempotency tests for structured fixtures."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_triage.config import AppSettings
from invoice_triage.domain import VendorStatus
from invoice_triage.ingestion import FixtureValidationError, load_structured_fixtures
from invoice_triage.storage import BudgetRepository, Database, VendorRepository


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
    try:
        _load(db)
        yield db
    finally:
        db.close()


def _load(database: Database) -> None:
    result = load_structured_fixtures(
        database,
        vendors_path=FIXTURES / "vendors/vendors.csv",
        budgets_path=FIXTURES / "budgets/monthly_budgets.csv",
    )
    assert result.vendors_upserted == 18
    assert result.budgets_upserted == 13


def test_fixture_load_is_idempotent(database: Database) -> None:
    _load(database)
    _load(database)

    with database.connection() as connection:
        assert VendorRepository().count(connection) == 18
        assert BudgetRepository().count(connection) == 13


def test_vendor_lookup_by_id_and_alias(database: Database) -> None:
    repository = VendorRepository()
    with database.connection() as connection:
        apex = repository.get_by_id(connection, "VND-1010")
        northstar = repository.find_by_name_or_alias(connection, "ncs cloud")

    assert apex is not None
    assert apex.status is VendorStatus.INACTIVE
    assert apex.default_cost_center == "TECH-PROJECTS"
    assert len(northstar) == 1
    assert northstar[0].vendor_id == "VND-1001"


def test_budget_lookup_preserves_current_base_commitment(database: Database) -> None:
    with database.connection() as connection:
        budget = BudgetRepository().get(
            connection,
            budget_period=date(2026, 7, 1),
            category="facilities_maintenance",
            cost_center="FACILITIES",
        )

    assert budget is not None
    assert budget.budget_amount == Decimal("12500.00")
    assert budget.committed_amount == Decimal("5000.00")


def test_invalid_budget_prevents_vendor_changes(
    database: Database,
    tmp_path: Path,
) -> None:
    original_vendor_file = FIXTURES / "vendors/vendors.csv"
    changed_vendor_file = tmp_path / "vendors.csv"
    changed_vendor_file.write_text(
        original_vendor_file.read_text(encoding="utf-8").replace(
            "Northstar Cloud Services LLC",
            "Name That Must Not Be Loaded",
            1,
        ),
        encoding="utf-8",
    )
    invalid_budget_file = tmp_path / "budgets.csv"
    invalid_budget_file.write_text(
        "budget_period,category,cost_center,budget_amount,"
        "committed_before_fixture_invoices,currency,owner\n"
        "2026-99,cloud_software,TECH-OPS,1.00,0.00,USD,Owner\n",
        encoding="utf-8",
    )

    with pytest.raises(FixtureValidationError):
        load_structured_fixtures(
            database,
            vendors_path=changed_vendor_file,
            budgets_path=invalid_budget_file,
        )

    with database.connection() as connection:
        northstar = VendorRepository().get_by_id(connection, "VND-1001")
    assert northstar is not None
    assert northstar.legal_name == "Northstar Cloud Services LLC"
