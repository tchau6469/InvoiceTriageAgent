"""Ensure structured fixtures conform to the Step 1 domain vocabulary."""

import csv
from decimal import Decimal
from pathlib import Path

from invoice_triage.domain import BudgetCheck, Vendor, VendorContact


FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_all_vendor_rows_validate_as_vendor_models() -> None:
    with (FIXTURES / "vendors/vendors.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))

    vendors = [
        Vendor(
            vendor_id=row["vendor_id"],
            legal_name=row["legal_name"],
            display_name=row["display_name"],
            aliases=tuple(row["aliases"].split("|")),
            status=row["status"],
            category=row["category"],
            historical_spend_12m=row["historical_spend_12m"],
            currency=row["currency"],
            default_payment_terms=row["default_payment_terms"],
            default_cost_center=row["default_cost_center"],
            contact=VendorContact(
                name=row["contact_name"],
                title=row["contact_title"],
                email=row["contact_email"],
                phone=row["contact_phone"],
            ),
            contract_file=row["contract_file"],
            remittance_profile_ref=row["remittance_profile_ref"],
        )
        for row in rows
    ]

    assert len(vendors) == 18
    assert len({vendor.vendor_id for vendor in vendors}) == 18
    assert all(vendor.historical_spend_12m > Decimal("0") for vendor in vendors)


def test_all_budget_rows_conform_to_budget_vocabulary() -> None:
    with (FIXTURES / "budgets/monthly_budgets.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))

    checks = [
        BudgetCheck(
            budget_period=row["budget_period"],
            category=row["category"],
            expected_cost_center=row["cost_center"],
            invoice_cost_center=row["cost_center"],
            currency=row["currency"],
            budget_amount=row["budget_amount"],
            committed_amount=row["committed_before_fixture_invoices"],
            invoice_amount="0",
        )
        for row in rows
    ]

    assert len(checks) == 13
