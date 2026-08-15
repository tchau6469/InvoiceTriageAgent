"""Strict, token-conscious output contracts for MCP tools."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

from invoice_triage.domain import (
    BudgetStatus,
    DocumentStatus,
    DuplicateReason,
    InvoiceIdentifierType,
    InvoiceRecordStatus,
    PaymentTerms,
    VendorCategory,
    VendorStatus,
)
from invoice_triage.retrieval import RetrievalMode


ExactDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^-?(0|[1-9]\d*)(\.\d+)?$",
            "description": "Exact base-10 decimal serialized as a string",
        }
    ),
]


class MCPModel(BaseModel):
    """Reject accidental schema expansion at the agent boundary."""

    model_config = ConfigDict(extra="forbid")


class EvidenceStatus(StrEnum):
    """Distinguish valid no-match retrieval from infrastructure failure."""

    FOUND = "found"
    NOT_FOUND = "not_found"


class VendorLookupStatus(StrEnum):
    """Describe whether a vendor identifier resolved uniquely."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


class VendorMatchType(StrEnum):
    """How a vendor-master result matched the caller's identifier."""

    VENDOR_ID = "vendor_id"
    NAME_OR_ALIAS = "name_or_alias"


class BudgetCheckStatus(StrEnum):
    """Separate evaluated business outcomes from missing prerequisite data."""

    EVALUATED = "evaluated"
    INVOICE_NOT_FOUND = "invoice_not_found"
    VENDOR_NOT_FOUND = "vendor_not_found"
    BUDGET_NOT_FOUND = "budget_not_found"
    CURRENCY_MISMATCH = "currency_mismatch"


class DuplicateCheckStatus(StrEnum):
    """Describe whether a persisted candidate could be evaluated."""

    EVALUATED = "evaluated"
    INVOICE_NOT_FOUND = "invoice_not_found"


class DuplicateFindingStatus(StrEnum):
    """High-level result derived from deterministic duplicate signals."""

    NO_DUPLICATE = "no_duplicate"
    POSSIBLE_DUPLICATE = "possible_duplicate"


class InvoiceExtractionStatus(StrEnum):
    """Describe whether a persisted invoice source could be extracted."""

    EXTRACTED = "extracted"
    INVOICE_NOT_FOUND = "invoice_not_found"
    SOURCE_UNAVAILABLE = "source_unavailable"


class GroundingDocumentType(StrEnum):
    """Document roles intentionally exposed through runtime grounding."""

    VENDOR_CONTRACT = "vendor_contract"
    SPENDING_POLICY = "spending_policy"


class AppliedRetrievalFilters(MCPModel):
    """Typed filters actually applied by the retrieval service."""

    category: VendorCategory | None = None
    vendor_id: str | None = None
    as_of_date: date | None = None


class RetrievalScores(MCPModel):
    """Diagnostic ranking scores; these are not confidence probabilities."""

    final: float
    vector: float | None = None
    lexical: float | None = None
    rrf: float | None = None
    reranker: float | None = None


class EvidenceDocument(MCPModel):
    """Allowlisted provenance needed for grounding and citations."""

    document_id: str
    document_type: GroundingDocumentType
    title: str
    section: str
    source_path: str
    status: DocumentStatus
    vendor_id: str | None = None
    category: VendorCategory | None = None
    effective_date: date | None = None
    expiration_date: date | None = None


class RetrievalEvidence(MCPModel):
    """One ranked grounding passage with a stable citation identifier."""

    citation_id: str
    rank: int = Field(ge=1)
    content: str = Field(min_length=1)
    document: EvidenceDocument
    scores: RetrievalScores


class RetrieveContextResponse(MCPModel):
    """Structured MCP result consumed by the future orchestration layer."""

    query: str = Field(min_length=1)
    mode: RetrievalMode
    filters: AppliedRetrievalFilters
    evidence_status: EvidenceStatus
    result_count: int = Field(ge=0, le=10)
    results: tuple[RetrievalEvidence, ...]


class VendorSummary(MCPModel):
    """Allowlisted operational vendor-master fields used during triage."""

    vendor_id: str
    legal_name: str
    display_name: str
    aliases: tuple[str, ...]
    status: VendorStatus
    category: VendorCategory
    historical_spend_12m: ExactDecimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    default_payment_terms: PaymentTerms
    default_cost_center: str
    contract_file: str


class VendorMatch(MCPModel):
    """One vendor result plus the deterministic match method."""

    match_type: VendorMatchType
    vendor: VendorSummary


class LookupVendorResponse(MCPModel):
    """Structured vendor resolution without contact/remittance details."""

    identifier: str = Field(min_length=1)
    lookup_status: VendorLookupStatus
    result_count: int = Field(ge=0)
    results: tuple[VendorMatch, ...]


class BudgetSnapshot(MCPModel):
    """Authoritative monthly budget record used for one check."""

    budget_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    category: VendorCategory
    cost_center: str
    budget_amount: ExactDecimal = Field(ge=0)
    base_committed_amount: ExactDecimal = Field(ge=0)
    persisted_committed_amount: ExactDecimal = Field(ge=0)
    committed_amount: ExactDecimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    owner: str


class BudgetEvaluation(MCPModel):
    """Deterministic projected-spend result for a candidate invoice."""

    status: BudgetStatus
    expected_cost_center: str
    invoice_cost_center: str
    invoice_amount: ExactDecimal = Field(ge=0)
    projected_spend: ExactDecimal
    remaining_after: ExactDecimal


class CheckBudgetResponse(MCPModel):
    """Budget lookup and evaluation with explicit prerequisite failures."""

    invoice_id: str
    check_status: BudgetCheckStatus
    vendor: VendorSummary | None = None
    budget: BudgetSnapshot | None = None
    evaluation: BudgetEvaluation | None = None


class InvoiceIdentifierSummary(MCPModel):
    """Allowlisted typed invoice reference."""

    identifier_type: InvoiceIdentifierType
    value: str


class InvoiceRecordSummary(MCPModel):
    """Allowlisted persisted invoice fields used to explain a check."""

    invoice_id: str
    vendor_invoice_number: str
    vendor_id: str
    invoice_date: date
    received_at: datetime
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total_due: ExactDecimal = Field(ge=0)
    cost_center: str
    record_status: InvoiceRecordStatus
    service_period_start: date | None = None
    service_period_end: date | None = None
    identifiers: tuple[InvoiceIdentifierSummary, ...]
    source_path: str


class DuplicateInvoiceMatch(MCPModel):
    """Earlier persisted record and every exact signal it shares."""

    invoice: InvoiceRecordSummary
    reasons: tuple[DuplicateReason, ...] = Field(min_length=1)
    matched_identifiers: tuple[InvoiceIdentifierSummary, ...]


class FlagDuplicateResponse(MCPModel):
    """Deterministic duplicate result for one persisted candidate invoice."""

    invoice_id: str
    check_status: DuplicateCheckStatus
    finding_status: DuplicateFindingStatus | None = None
    candidate: InvoiceRecordSummary | None = None
    match_count: int = Field(ge=0)
    matches: tuple[DuplicateInvoiceMatch, ...]


class ExtractedInvoiceLine(MCPModel):
    """One model-extracted line after application-domain validation."""

    description: str = Field(min_length=1)
    quantity: ExactDecimal = Field(gt=0)
    unit_price: ExactDecimal = Field(ge=0)
    amount: ExactDecimal = Field(ge=0)
    sku: str | None = None


class ExtractedInvoice(MCPModel):
    """Allowlisted normalized invoice fields returned by extraction."""

    invoice_id: str = Field(min_length=1)
    vendor_invoice_number: str = Field(min_length=1)
    vendor_id: str = Field(min_length=1)
    invoice_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total_due: ExactDecimal = Field(ge=0)
    lines: tuple[ExtractedInvoiceLine, ...] = Field(min_length=1)
    payment_terms: PaymentTerms | None = None
    cost_center: str | None = None
    po_number: str | None = None
    service_period_start: date | None = None
    service_period_end: date | None = None


class ModelTokenUsage(MCPModel):
    """Provider-reported token counts for cost and latency evaluation."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ExtractInvoiceResponse(MCPModel):
    """Validated extraction outcome for one allowlisted invoice source."""

    invoice_id: str = Field(min_length=1)
    extraction_status: InvoiceExtractionStatus
    extracted_invoice: ExtractedInvoice | None = None
    model_id: str | None = None
    usage: ModelTokenUsage | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ExtractInvoiceResponse":
        extracted = self.extraction_status is InvoiceExtractionStatus.EXTRACTED
        if extracted != (self.extracted_invoice is not None):
            raise ValueError(
                "extracted_invoice must be present exactly when status is extracted"
            )
        if extracted != (self.model_id is not None):
            raise ValueError("model_id must be present exactly when status is extracted")
        if self.extracted_invoice is not None:
            if self.extracted_invoice.invoice_id != self.invoice_id:
                raise ValueError("extracted invoice ID must match the requested ID")
        return self
