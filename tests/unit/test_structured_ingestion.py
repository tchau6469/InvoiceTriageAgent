"""Unit tests for structured fixture parsing before database access."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_triage.domain import VendorStatus
from invoice_triage.ingestion import (
    FixtureValidationError,
    read_budget_fixtures,
    read_vendor_fixtures,
)


FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_vendor_fixture_maps_all_rows_and_aliases() -> None:
    vendors = read_vendor_fixtures(FIXTURES / "vendors/vendors.csv")

    assert len(vendors) == 18
    assert len({vendor.vendor_id for vendor in vendors}) == 18
    assert vendors[0].aliases == ("Northstar Cloud", "NCS Cloud")
    assert next(v for v in vendors if v.vendor_id == "VND-1010").status is (
        VendorStatus.INACTIVE
    )


def test_budget_fixture_converts_month_to_first_day() -> None:
    budgets = read_budget_fixtures(FIXTURES / "budgets/monthly_budgets.csv")

    facilities = next(
        budget
        for budget in budgets
        if budget.category.value == "facilities_maintenance"
    )
    assert len(budgets) == 13
    assert facilities.budget_period == date(2026, 7, 1)
    assert facilities.budget_amount == Decimal("12500.00")
    assert facilities.committed_amount == Decimal("5000.00")


def test_vendor_fixture_rejects_wrong_header(tmp_path: Path) -> None:
    fixture = tmp_path / "vendors.csv"
    fixture.write_text("vendor_id,legal_name\nVND-1,Incomplete\n", encoding="utf-8")

    with pytest.raises(FixtureValidationError, match="expected columns"):
        read_vendor_fixtures(fixture)


def test_vendor_fixture_rejects_duplicate_ids(tmp_path: Path) -> None:
    header = (FIXTURES / "vendors/vendors.csv").read_text(encoding="utf-8").splitlines()[0]
    row = (FIXTURES / "vendors/vendors.csv").read_text(encoding="utf-8").splitlines()[1]
    fixture = tmp_path / "vendors.csv"
    fixture.write_text(f"{header}\n{row}\n{row}\n", encoding="utf-8")

    with pytest.raises(FixtureValidationError, match="duplicate vendor_id"):
        read_vendor_fixtures(fixture)


@pytest.mark.parametrize("period", ["2026-13", "July-2026", "2026-07-01"])
def test_budget_fixture_rejects_invalid_period(
    tmp_path: Path,
    period: str,
) -> None:
    fixture = tmp_path / "budgets.csv"
    fixture.write_text(
        "budget_period,category,cost_center,budget_amount,"
        "committed_before_fixture_invoices,currency,owner\n"
        f"{period},cloud_software,TECH-OPS,100.00,50.00,USD,Owner\n",
        encoding="utf-8",
    )

    with pytest.raises(FixtureValidationError, match="invalid budget row"):
        read_budget_fixtures(fixture)
