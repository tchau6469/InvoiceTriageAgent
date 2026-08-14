"""Validated, transactional loading for structured vendor and budget fixtures."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypeAlias

from pydantic import ValidationError

from invoice_triage.domain import MonthlyBudget, Vendor, VendorContact
from invoice_triage.storage import BudgetRepository, Database, VendorRepository


PathLike: TypeAlias = str | Path

VENDOR_COLUMNS = (
    "vendor_id",
    "legal_name",
    "display_name",
    "aliases",
    "status",
    "category",
    "historical_spend_12m",
    "currency",
    "default_payment_terms",
    "default_cost_center",
    "contact_name",
    "contact_title",
    "contact_email",
    "contact_phone",
    "contract_file",
    "remittance_profile_ref",
)

BUDGET_COLUMNS = (
    "budget_period",
    "category",
    "cost_center",
    "budget_amount",
    "committed_before_fixture_invoices",
    "currency",
    "owner",
)


class FixtureValidationError(ValueError):
    """A structured fixture cannot be safely loaded."""


@dataclass(frozen=True, slots=True)
class StructuredLoadResult:
    """Summary of records presented to idempotent database upserts."""

    vendors_upserted: int
    budgets_upserted: int


def read_vendor_fixtures(path: PathLike) -> tuple[Vendor, ...]:
    """Parse and validate an entire vendor-master CSV before database access."""

    source = Path(path)
    rows = _read_csv(source, VENDOR_COLUMNS)
    vendors: list[Vendor] = []

    for line_number, row in rows:
        try:
            vendors.append(
                Vendor(
                    vendor_id=row["vendor_id"],
                    legal_name=row["legal_name"],
                    display_name=row["display_name"],
                    aliases=tuple(
                        alias.strip()
                        for alias in row["aliases"].split("|")
                        if alias.strip()
                    ),
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
            )
        except ValidationError as exc:
            raise FixtureValidationError(
                f"{source}:{line_number}: invalid vendor row: {exc}"
            ) from exc

    _reject_duplicate_keys(
        source,
        ((vendor.vendor_id,) for vendor in vendors),
        "vendor_id",
    )
    return tuple(vendors)


def read_budget_fixtures(path: PathLike) -> tuple[MonthlyBudget, ...]:
    """Parse and validate an entire monthly-budget CSV before database access."""

    source = Path(path)
    rows = _read_csv(source, BUDGET_COLUMNS)
    budgets: list[MonthlyBudget] = []

    for line_number, row in rows:
        try:
            period = date.fromisoformat(f'{row["budget_period"]}-01')
            budgets.append(
                MonthlyBudget(
                    budget_period=period,
                    category=row["category"],
                    cost_center=row["cost_center"],
                    budget_amount=row["budget_amount"],
                    committed_amount=row["committed_before_fixture_invoices"],
                    currency=row["currency"],
                    owner=row["owner"],
                )
            )
        except (ValidationError, ValueError) as exc:
            raise FixtureValidationError(
                f"{source}:{line_number}: invalid budget row: {exc}"
            ) from exc

    _reject_duplicate_keys(
        source,
        (
            (budget.budget_period, budget.category.value, budget.cost_center)
            for budget in budgets
        ),
        "budget_period/category/cost_center",
    )
    return tuple(budgets)


def load_structured_fixtures(
    database: Database,
    *,
    vendors_path: PathLike,
    budgets_path: PathLike,
) -> StructuredLoadResult:
    """Validate both files, then atomically upsert both structured datasets."""

    # Both files are fully validated before opening a transaction. Database
    # constraints remain the second defensive layer.
    vendors = read_vendor_fixtures(vendors_path)
    budgets = read_budget_fixtures(budgets_path)

    vendor_repository = VendorRepository()
    budget_repository = BudgetRepository()
    with database.connection() as connection:
        vendor_count = vendor_repository.upsert_many(connection, vendors)
        budget_count = budget_repository.upsert_many(connection, budgets)

    return StructuredLoadResult(
        vendors_upserted=vendor_count,
        budgets_upserted=budget_count,
    )


def _read_csv(
    path: Path,
    expected_columns: tuple[str, ...],
) -> list[tuple[int, dict[str, str]]]:
    if not path.is_file():
        raise FixtureValidationError(f"structured fixture not found: {path}")

    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        actual_columns = tuple(reader.fieldnames or ())
        if actual_columns != expected_columns:
            raise FixtureValidationError(
                f"{path}: expected columns {expected_columns}, got {actual_columns}"
            )

        rows: list[tuple[int, dict[str, str]]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise FixtureValidationError(
                    f"{path}:{line_number}: row has more fields than the header"
                )
            if any(value is None for value in row.values()):
                raise FixtureValidationError(
                    f"{path}:{line_number}: row has fewer fields than the header"
                )
            rows.append((line_number, row))

    if not rows:
        raise FixtureValidationError(f"{path}: fixture contains no data rows")
    return rows


def _reject_duplicate_keys(
    path: Path,
    keys: Iterable[tuple[object, ...]],
    label: str,
) -> None:
    seen: set[tuple[object, ...]] = set()
    for key in keys:
        if key in seen:
            rendered = "/".join(str(part) for part in key)
            raise FixtureValidationError(
                f"{path}: duplicate {label} key: {rendered}"
            )
        seen.add(key)
