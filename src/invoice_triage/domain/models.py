"""Strict data contracts for documents, invoices, retrieval, and controls."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    computed_field,
    model_validator,
)


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{3}$"),
]
BudgetPeriod = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
]
NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"))]
PositiveDecimal = Annotated[Decimal, Field(gt=Decimal("0"))]
Metadata = dict[str, JsonValue]


class DomainModel(BaseModel):
    """Base behavior for values exchanged between pipeline stages."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class DocumentType(StrEnum):
    """Supported source-document roles."""

    VENDOR_CONTRACT = "vendor_contract"
    SPENDING_POLICY = "spending_policy"
    INVOICE = "invoice"


class DocumentStatus(StrEnum):
    """Lifecycle state retained as retrieval metadata."""

    ACTIVE = "active"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    HISTORICAL = "historical"


class VendorStatus(StrEnum):
    """Operational vendor state used during invoice triage."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class VendorCategory(StrEnum):
    """Categories represented by the synthetic corpus."""

    CLOUD_SOFTWARE = "cloud_software"
    OFFICE_SUPPLIES = "office_supplies"
    FACILITIES_MAINTENANCE = "facilities_maintenance"
    PROFESSIONAL_SERVICES = "professional_services"
    LOGISTICS_FREIGHT = "logistics_freight"
    MARKETING_EVENTS = "marketing_events"


class PaymentTerms(StrEnum):
    """Contractual payment terms currently represented by the corpus."""

    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_45 = "NET_45"


class BudgetStatus(StrEnum):
    """Deterministic result of a structured budget check."""

    WITHIN_BUDGET = "within_budget"
    BUDGET_EXCEEDED = "budget_exceeded"
    COST_CENTER_MISMATCH = "cost_center_mismatch"


class SourceDocument(DomainModel):
    """Validated representation produced by a source-file parser."""

    document_id: NonEmptyString
    document_type: DocumentType
    title: NonEmptyString
    content: NonEmptyString
    source_path: NonEmptyString
    status: DocumentStatus = DocumentStatus.ACTIVE
    vendor_id: NonEmptyString | None = None
    category: VendorCategory | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    metadata: Metadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_document_scope(self) -> Self:
        """Ensure lifecycle dates and required routing metadata are coherent."""

        if (
            self.effective_date is not None
            and self.expiration_date is not None
            and self.expiration_date < self.effective_date
        ):
            raise ValueError("expiration_date cannot precede effective_date")

        if self.document_type in {
            DocumentType.VENDOR_CONTRACT,
            DocumentType.INVOICE,
        } and self.vendor_id is None:
            raise ValueError(f"{self.document_type.value} requires vendor_id")

        if self.document_type in {
            DocumentType.VENDOR_CONTRACT,
            DocumentType.SPENDING_POLICY,
        } and self.category is None:
            raise ValueError(f"{self.document_type.value} requires category")

        return self


class DocumentChunk(DomainModel):
    """Retrieval unit with enough provenance to explain every result."""

    chunk_id: NonEmptyString
    document_id: NonEmptyString
    document_type: DocumentType
    section: NonEmptyString
    ordinal: int = Field(ge=0)
    content: NonEmptyString
    source_path: NonEmptyString
    status: DocumentStatus = DocumentStatus.ACTIVE
    vendor_id: NonEmptyString | None = None
    category: VendorCategory | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    metadata: Metadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_lifecycle_dates(self) -> Self:
        """Reject impossible contract lifecycles copied into chunk metadata."""

        if (
            self.effective_date is not None
            and self.expiration_date is not None
            and self.expiration_date < self.effective_date
        ):
            raise ValueError("expiration_date cannot precede effective_date")
        return self


class VendorContact(DomainModel):
    """Synthetic operational contact associated with a vendor."""

    name: NonEmptyString
    title: NonEmptyString
    email: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        ),
    ]
    phone: NonEmptyString


class Vendor(DomainModel):
    """Structured vendor-master record used by vendor lookup."""

    vendor_id: NonEmptyString
    legal_name: NonEmptyString
    display_name: NonEmptyString
    aliases: tuple[NonEmptyString, ...] = ()
    status: VendorStatus
    category: VendorCategory
    historical_spend_12m: NonNegativeDecimal
    currency: CurrencyCode
    default_payment_terms: PaymentTerms
    default_cost_center: NonEmptyString
    contact: VendorContact
    contract_file: NonEmptyString
    remittance_profile_ref: NonEmptyString


class MonthlyBudget(DomainModel):
    """Authoritative monthly budget imported from a structured finance source."""

    budget_period: date
    category: VendorCategory
    cost_center: NonEmptyString
    budget_amount: NonNegativeDecimal
    committed_amount: NonNegativeDecimal
    currency: CurrencyCode
    owner: NonEmptyString

    @model_validator(mode="after")
    def validate_budget_period_and_amounts(self) -> Self:
        """Require a first-of-month period and internally consistent amounts."""

        if self.budget_period.day != 1:
            raise ValueError("budget_period must be the first day of a month")
        if self.committed_amount > self.budget_amount:
            raise ValueError("committed_amount cannot exceed budget_amount")
        return self


class InvoiceLine(DomainModel):
    """Extracted invoice line; arithmetic discrepancies are evaluated later."""

    description: NonEmptyString
    quantity: PositiveDecimal
    unit_price: NonNegativeDecimal
    amount: NonNegativeDecimal
    sku: NonEmptyString | None = None


class Invoice(DomainModel):
    """Normalized invoice passed to deterministic checks and the agent."""

    invoice_id: NonEmptyString
    vendor_invoice_number: NonEmptyString
    vendor_id: NonEmptyString
    invoice_date: date
    currency: CurrencyCode
    total_due: NonNegativeDecimal
    lines: tuple[InvoiceLine, ...] = Field(min_length=1)
    payment_terms: PaymentTerms | None = None
    cost_center: NonEmptyString | None = None
    po_number: NonEmptyString | None = None
    service_period_start: date | None = None
    service_period_end: date | None = None
    metadata: Metadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_service_period(self) -> Self:
        """Ensure a fully specified service period has a valid date order."""

        if (self.service_period_start is None) != (self.service_period_end is None):
            raise ValueError(
                "service_period_start and service_period_end must be provided together"
            )
        if (
            self.service_period_start is not None
            and self.service_period_end is not None
            and self.service_period_end < self.service_period_start
        ):
            raise ValueError("service_period_end cannot precede service_period_start")
        return self


class RetrievalQuery(DomainModel):
    """Search request shared by vector, keyword, hybrid, and reranked modes."""

    query: NonEmptyString
    top_k: int = Field(default=5, ge=1, le=100)
    category: VendorCategory | None = None
    vendor_id: NonEmptyString | None = None
    include_expired: bool = False
    metadata_filter: Metadata = Field(default_factory=dict)


class SearchResult(DomainModel):
    """Ranked retrieval result with stage-specific scores and provenance."""

    chunk: DocumentChunk
    rank: int = Field(ge=1)
    combined_score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    reranker_score: float | None = None

    @computed_field
    @property
    def final_score(self) -> float:
        """Expose the score used by the final available ranking stage."""

        if self.reranker_score is not None:
            return self.reranker_score
        return self.combined_score


class BudgetCheck(DomainModel):
    """Inputs and deterministic outcome for a single budget validation."""

    budget_period: BudgetPeriod
    category: VendorCategory
    expected_cost_center: NonEmptyString
    invoice_cost_center: NonEmptyString
    currency: CurrencyCode
    budget_amount: NonNegativeDecimal
    committed_amount: NonNegativeDecimal
    invoice_amount: NonNegativeDecimal

    @computed_field
    @property
    def projected_spend(self) -> Decimal:
        """Committed spend after including the candidate invoice."""

        return self.committed_amount + self.invoice_amount

    @computed_field
    @property
    def remaining_after(self) -> Decimal:
        """Budget remaining after the candidate invoice; negative means over."""

        return self.budget_amount - self.projected_spend

    @computed_field
    @property
    def status(self) -> BudgetStatus:
        """Prioritize coding mismatches before checking available amount."""

        if self.invoice_cost_center != self.expected_cost_center:
            return BudgetStatus.COST_CENTER_MISMATCH
        if self.projected_spend > self.budget_amount:
            return BudgetStatus.BUDGET_EXCEEDED
        return BudgetStatus.WITHIN_BUDGET
