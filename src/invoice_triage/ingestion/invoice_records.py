"""Strict parsing and transactional loading for Markdown invoice records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
import re
from typing import TypeAlias

from pydantic import ValidationError

from invoice_triage.domain import (
    InvoiceIdentifier,
    InvoiceIdentifierType,
    PersistedInvoice,
)
from invoice_triage.ingestion.parser import _portable_source_path, _split_front_matter
from invoice_triage.storage import Database, InvoiceRepository


PathLike: TypeAlias = str | Path

_ALLOWED_FRONT_MATTER = {
    "invoice_id",
    "vendor_invoice_number",
    "vendor_id",
    "invoice_date",
    "currency",
    "record_status",
    "received_at",
}
_TOTAL_PATTERN = re.compile(
    r"\*\*Total due:\s*\$([0-9][0-9,]*(?:\.[0-9]{2})?)\*\*",
    re.IGNORECASE,
)
_COST_CENTER_PATTERN = re.compile(
    r"^Cost center:\s*`([^`]+)`\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PERIOD_PATTERN = re.compile(
    r"^(?:Service|Billing) period:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SAME_MONTH_PERIOD = re.compile(
    r"^([A-Za-z]+)\s+(\d{1,2})\s*[–-]\s*(\d{1,2}),\s*(\d{4})$"
)
_CROSS_MONTH_PERIOD = re.compile(
    r"^([A-Za-z]+)\s+(\d{1,2})\s*[–-]\s*([A-Za-z]+)\s+"
    r"(\d{1,2}),\s*(\d{4})$"
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_IDENTIFIER_PATTERNS = {
    InvoiceIdentifierType.BILL_OF_LADING: re.compile(
        r"^Bill of lading:\s*`([^`]+)`\s*$", re.IGNORECASE | re.MULTILINE
    ),
    InvoiceIdentifierType.TRACKING_NUMBER: re.compile(
        r"^Tracking number:\s*`([^`]+)`\s*$", re.IGNORECASE | re.MULTILINE
    ),
    InvoiceIdentifierType.PACKING_SLIP: re.compile(
        r"^Packing slip:\s*`([^`]+)`\s*$", re.IGNORECASE | re.MULTILINE
    ),
    InvoiceIdentifierType.PROOF_OF_DELIVERY: re.compile(
        r"^Proof of delivery:\s*`([^`]+)`\s*$", re.IGNORECASE | re.MULTILINE
    ),
    InvoiceIdentifierType.PURCHASE_ORDER: re.compile(
        r"^PO:\s*`([^`]+)`\s*$", re.IGNORECASE | re.MULTILINE
    ),
}


class InvoiceFixtureError(ValueError):
    """An invoice fixture cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class InvoiceLoadResult:
    """Summary of invoice records presented to the idempotent repository."""

    invoices_upserted: int
    identifiers_upserted: int


def parse_invoice_record(
    path: PathLike,
    *,
    source_root: PathLike | None = None,
) -> PersistedInvoice:
    """Parse one Markdown invoice into fields required by structured checks."""

    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InvoiceFixtureError(f"cannot read invoice source {source}: {exc}") from exc

    front_matter, body = _split_front_matter(raw, source)
    portable_path = _portable_source_path(
        source,
        Path(source_root) if source_root is not None else None,
    )
    unknown = set(front_matter) - _ALLOWED_FRONT_MATTER
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise InvoiceFixtureError(
            f"{portable_path}: unknown invoice front-matter fields: {fields}"
        )
    missing = _ALLOWED_FRONT_MATTER - set(front_matter)
    if missing:
        fields = ", ".join(sorted(missing))
        raise InvoiceFixtureError(
            f"{portable_path}: missing invoice front-matter fields: {fields}"
        )

    total_match = _TOTAL_PATTERN.search(body)
    cost_center_match = _COST_CENTER_PATTERN.search(body)
    if total_match is None:
        raise InvoiceFixtureError(f"{portable_path}: total due was not found")
    if cost_center_match is None:
        raise InvoiceFixtureError(f"{portable_path}: cost center was not found")

    service_start, service_end = _service_period(body, portable_path)
    identifiers = tuple(
        InvoiceIdentifier(identifier_type=identifier_type, value=match.group(1))
        for identifier_type, pattern in _IDENTIFIER_PATTERNS.items()
        if (match := pattern.search(body)) is not None
    )
    try:
        return PersistedInvoice(
            **front_matter,
            total_due=total_match.group(1).replace(",", ""),
            cost_center=cost_center_match.group(1),
            service_period_start=service_start,
            service_period_end=service_end,
            identifiers=identifiers,
            source_path=portable_path,
            content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        )
    except ValidationError as exc:
        raise InvoiceFixtureError(
            f"{portable_path}: invalid normalized invoice: {exc}"
        ) from exc


def discover_invoice_sources(root: PathLike) -> tuple[Path, ...]:
    """Discover only Markdown invoice inputs, never evaluation labels."""

    invoice_root = Path(root) / "invoices"
    sources = tuple(sorted(invoice_root.glob("*.md")))
    if not sources:
        raise InvoiceFixtureError(f"no invoice Markdown files found under {invoice_root}")
    return sources


def read_invoice_fixtures(root: PathLike) -> tuple[PersistedInvoice, ...]:
    """Validate the complete invoice fixture set before database access."""

    source_root = Path(root)
    invoices = tuple(
        parse_invoice_record(path, source_root=source_root.parent)
        for path in discover_invoice_sources(source_root)
    )
    _reject_duplicate_invoice_fields(invoices, source_root)
    return invoices


def load_invoice_fixtures(
    database: Database,
    *,
    fixtures_root: PathLike,
) -> InvoiceLoadResult:
    """Validate and atomically upsert invoice records and identifiers."""

    invoices = read_invoice_fixtures(fixtures_root)
    with database.connection() as connection:
        invoice_count, identifier_count = InvoiceRepository().upsert_many(
            connection,
            invoices,
        )
    return InvoiceLoadResult(
        invoices_upserted=invoice_count,
        identifiers_upserted=identifier_count,
    )


def _service_period(body: str, source_path: str) -> tuple[date | None, date | None]:
    match = _PERIOD_PATTERN.search(body)
    if match is None:
        return None, None
    value = match.group(1).strip()
    same_month = _SAME_MONTH_PERIOD.fullmatch(value)
    if same_month is not None:
        month_name, start_day, end_day, year = same_month.groups()
        month = _month(month_name, source_path)
        try:
            return (
                date(int(year), month, int(start_day)),
                date(int(year), month, int(end_day)),
            )
        except ValueError as exc:
            raise InvoiceFixtureError(
                f"{source_path}: invalid service period: {value}"
            ) from exc

    cross_month = _CROSS_MONTH_PERIOD.fullmatch(value)
    if cross_month is not None:
        start_month_name, start_day, end_month_name, end_day, year = (
            cross_month.groups()
        )
        try:
            return (
                date(int(year), _month(start_month_name, source_path), int(start_day)),
                date(int(year), _month(end_month_name, source_path), int(end_day)),
            )
        except ValueError as exc:
            raise InvoiceFixtureError(
                f"{source_path}: invalid service period: {value}"
            ) from exc
    raise InvoiceFixtureError(f"{source_path}: unsupported service period: {value}")


def _month(value: str, source_path: str) -> int:
    try:
        return _MONTHS[value.casefold()]
    except KeyError as exc:
        raise InvoiceFixtureError(
            f"{source_path}: unrecognized month in service period: {value}"
        ) from exc


def _reject_duplicate_invoice_fields(
    invoices: tuple[PersistedInvoice, ...],
    root: Path,
) -> None:
    invoice_ids: set[str] = set()
    source_paths: set[str] = set()
    for invoice in invoices:
        if invoice.invoice_id in invoice_ids:
            raise InvoiceFixtureError(
                f"{root}: duplicate invoice_id: {invoice.invoice_id}"
            )
        if invoice.source_path in source_paths:
            raise InvoiceFixtureError(
                f"{root}: duplicate invoice source_path: {invoice.source_path}"
            )
        invoice_ids.add(invoice.invoice_id)
        source_paths.add(invoice.source_path)
