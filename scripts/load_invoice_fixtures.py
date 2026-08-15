"""Load validated Markdown invoice records into PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from invoice_triage.config import AppSettings
from invoice_triage.ingestion import load_invoice_fixtures
from invoice_triage.storage import Database


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and transactionally upsert Markdown invoice records."
    )
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=REPOSITORY_ROOT / "fixtures",
        help="fixture directory containing invoices/",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = AppSettings.from_environment()
    with Database.from_settings(settings) as database:
        result = load_invoice_fixtures(
            database,
            fixtures_root=args.fixtures_root,
        )
    print(
        "Invoice fixtures loaded: "
        f"invoices={result.invoices_upserted}, "
        f"identifiers={result.identifiers_upserted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
