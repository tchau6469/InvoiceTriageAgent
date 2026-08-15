"""Narrow model-facing schema for invoice field extraction."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from invoice_triage.domain import Invoice, InvoiceLine, PaymentTerms


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
UnsignedDecimalText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(0|[1-9]\d*)(\.\d+)?$",
    ),
]
PositiveDecimalText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(?:0*\.[0-9]*[1-9][0-9]*|[1-9]\d*(?:\.\d+)?)$",
    ),
]


class ExtractionModel(BaseModel):
    """Strict schema sent to a structured-output provider."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InvoiceLineExtractionPayload(ExtractionModel):
    """One extracted row, with exact decimal values represented as strings."""

    description: NonEmptyText = Field(
        description="Invoice line description copied from the source"
    )
    quantity: PositiveDecimalText = Field(
        description="Numeric quantity only, without a unit label"
    )
    unit_price: UnsignedDecimalText = Field(
        description="Unit price without currency symbols or thousands separators"
    )
    amount: UnsignedDecimalText = Field(
        description="Line amount without currency symbols or thousands separators"
    )
    sku: NonEmptyText | None = Field(
        default=None,
        description="Explicit SKU or item code, otherwise null",
    )


class InvoiceExtractionPayload(ExtractionModel):
    """Provider-facing invoice fields that convert into the domain contract."""

    invoice_id: NonEmptyText
    vendor_invoice_number: NonEmptyText
    vendor_id: NonEmptyText
    invoice_date: date
    currency: Annotated[
        str,
        StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{3}$"),
    ]
    total_due: UnsignedDecimalText
    lines: tuple[InvoiceLineExtractionPayload, ...] = Field(min_length=1)
    payment_terms: PaymentTerms | None = None
    cost_center: NonEmptyText | None = None
    po_number: NonEmptyText | None = None
    service_period_start: date | None = None
    service_period_end: date | None = None

    def to_domain(self) -> Invoice:
        """Apply the stricter application-domain validation after generation."""

        return Invoice(
            invoice_id=self.invoice_id,
            vendor_invoice_number=self.vendor_invoice_number,
            vendor_id=self.vendor_id,
            invoice_date=self.invoice_date,
            currency=self.currency,
            total_due=self.total_due,
            lines=tuple(
                InvoiceLine(
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=line.amount,
                    sku=line.sku,
                )
                for line in self.lines
            ),
            payment_terms=self.payment_terms,
            cost_center=self.cost_center,
            po_number=self.po_number,
            service_period_start=self.service_period_start,
            service_period_end=self.service_period_end,
            metadata={},
        )
