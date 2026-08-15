"""Tests for provider-neutral extraction and the Gemini adapter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from invoice_triage.reasoning import InvoiceExtractionPayload
from invoice_triage.reasoning.gemini import (
    GeminiReasoningClient,
    GeminiReasoningError,
)


def _payload() -> InvoiceExtractionPayload:
    return InvoiceExtractionPayload(
        invoice_id="INV-2026-0019",
        vendor_invoice_number="CFG-EM-2026-119",
        vendor_id="VND-1007",
        invoice_date="2026-07-24",
        currency="USD",
        total_due="1450.00",
        lines=(
            {
                "description": "Emergency water-response labor",
                "quantity": "10",
                "unit_price": "145.00",
                "amount": "1450.00",
                "sku": None,
            },
        ),
        payment_terms="NET_30",
        cost_center="FACILITIES",
        po_number="PO-2026-2291",
    )


def test_extraction_payload_converts_to_domain_invoice() -> None:
    invoice = _payload().to_domain()

    assert invoice.invoice_id == "INV-2026-0019"
    assert str(invoice.total_due) == "1450.00"
    assert str(invoice.lines[0].quantity) == "10"
    assert invoice.metadata == {}


def test_gemini_adapter_uses_structured_schema_and_reports_usage() -> None:
    async def exercise() -> None:
        models = StaticModels(
            SimpleNamespace(
                parsed=_payload(),
                text=None,
                usage_metadata=SimpleNamespace(
                    prompt_token_count=120,
                    candidates_token_count=45,
                    total_token_count=165,
                ),
            )
        )
        client = GeminiReasoningClient(
            api_key="test-key",
            model_id="gemini-test",
            async_client=SimpleNamespace(models=models),
        )

        result = await client.generate_structured(
            system_instruction="Extract only.",
            prompt="Synthetic invoice",
            response_model=InvoiceExtractionPayload,
        )

        assert result.value.invoice_id == "INV-2026-0019"
        assert result.model_id == "gemini-test"
        assert result.usage.total_tokens == 165
        assert models.last_call is not None
        assert models.last_call["config"]["response_mime_type"] == "application/json"
        response_schema = models.last_call["config"]["response_json_schema"]
        assert response_schema["additionalProperties"] is False
        assert "lines" in response_schema["properties"]
        assert models.last_call["config"]["automatic_function_calling"] == {
            "disable": True
        }
        assert models.last_call["config"]["system_instruction"] == "Extract only."

    asyncio.run(exercise())


def test_gemini_adapter_rejects_invalid_json_response() -> None:
    async def exercise() -> None:
        models = StaticModels(
            SimpleNamespace(parsed=None, text='{"unexpected": true}', usage_metadata=None)
        )
        client = GeminiReasoningClient(
            api_key="test-key",
            async_client=SimpleNamespace(models=models),
        )
        with pytest.raises(GeminiReasoningError):
            await client.generate_structured(
                system_instruction="Extract only.",
                prompt="Synthetic invoice",
                response_model=InvoiceExtractionPayload,
            )

    asyncio.run(exercise())


class StaticModels:
    def __init__(self, response: object) -> None:
        self.response = response
        self.last_call: dict[str, object] | None = None

    async def generate_content(self, **kwargs: object) -> object:
        self.last_call = kwargs
        return self.response
