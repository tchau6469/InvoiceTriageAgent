"""Load validated vendor and budget fixtures into PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from invoice_triage.config import AppSettings
from invoice_triage.ingestion import load_structured_fixtures
from invoice_triage.storage import Database


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and transactionally upsert structured fixtures."
    )
    parser.add_argument(
        "--vendors",
        type=Path,
        default=REPOSITORY_ROOT / "fixtures/vendors/vendors.csv",
        help="path to the vendor-master CSV",
    )
    parser.add_argument(
        "--budgets",
        type=Path,
        default=REPOSITORY_ROOT / "fixtures/budgets/monthly_budgets.csv",
        help="path to the monthly-budget CSV",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = AppSettings.from_environment()

    with Database.from_settings(settings) as database:
        result = load_structured_fixtures(
            database,
            vendors_path=args.vendors,
            budgets_path=args.budgets,
        )

    print(
        "Structured fixtures loaded: "
        f"vendors={result.vendors_upserted}, "
        f"budgets={result.budgets_upserted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
