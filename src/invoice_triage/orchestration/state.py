"""Validated shared state contract for the forthcoming LangGraph workflow."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from invoice_triage.mcp_server.models import (
    CheckBudgetResponse,
    ExtractInvoiceResponse,
    FlagDuplicateResponse,
    LookupVendorResponse,
    RetrieveContextResponse,
)


class TriageStage(StrEnum):
    """Last successfully completed workflow stage."""

    RECEIVED = "received"
    EXTRACTED = "extracted"
    VENDOR_CHECKED = "vendor_checked"
    DUPLICATE_CHECKED = "duplicate_checked"
    BUDGET_CHECKED = "budget_checked"
    CONTEXT_RETRIEVED = "context_retrieved"
    RECOMMENDATION_DRAFTED = "recommendation_drafted"
    HUMAN_REVIEW = "human_review"
    COMPLETE = "complete"


class TriageRoute(StrEnum):
    """Explicit conditional branch selected by deterministic nodes."""

    CONTINUE = "continue"
    MISSING_VENDOR = "missing_vendor"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    BUDGET_ANOMALY = "budget_anomaly"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HUMAN_REVIEW = "human_review"


class InvoiceTriageState(BaseModel):
    """Complete state passed between graph nodes.

    Nodes will return partial dictionaries, but each node adapter will rebuild
    this model so invalid intermediate state cannot silently reach a later step.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    invoice_id: str = Field(min_length=1)
    stage: TriageStage = TriageStage.RECEIVED
    route: TriageRoute = TriageRoute.CONTINUE
    extraction: ExtractInvoiceResponse | None = None
    vendor_lookup: LookupVendorResponse | None = None
    duplicate_check: FlagDuplicateResponse | None = None
    budget_check: CheckBudgetResponse | None = None
    retrieved_context: tuple[RetrieveContextResponse, ...] = ()
    recommendation: str | None = None
    review_reasons: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    requires_human_review: bool = True
