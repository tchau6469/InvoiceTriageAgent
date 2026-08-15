"""Tests for the shared LangGraph state contract."""

import pytest
from pydantic import ValidationError

from invoice_triage.orchestration import InvoiceTriageState, TriageRoute, TriageStage


def test_initial_triage_state_is_human_reviewed_by_default() -> None:
    state = InvoiceTriageState(invoice_id="INV-2026-0019")

    assert state.stage is TriageStage.RECEIVED
    assert state.route is TriageRoute.CONTINUE
    assert state.requires_human_review is True
    assert state.retrieved_context == ()


def test_triage_state_rejects_unknown_channels() -> None:
    with pytest.raises(ValidationError):
        InvoiceTriageState(invoice_id="INV-2026-0019", model_secret="nope")
