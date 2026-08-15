"""Protocol-level tests for FastMCP tool discovery and structured output."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator

from fastmcp import Client

from invoice_triage.mcp_server import RetrievalTool
from invoice_triage.mcp_server.models import (
    ExtractedInvoice,
    ExtractedInvoiceLine,
    ExtractInvoiceResponse,
    InvoiceExtractionStatus,
    ModelTokenUsage,
)
from invoice_triage.mcp_server.server import MCPRuntime, create_server
from tests.unit.test_mcp_retrieval import StaticService, _result
from tests.unit.test_mcp_structured_tools import (
    StaticBudgetRepository,
    StaticInvoiceRepository,
    StaticVendorRepository,
    _budget,
    _tool,
    _invoice,
    _vendor,
)


def test_mcp_schema_is_bounded_read_only_and_excludes_internal_controls() -> None:
    async def exercise() -> None:
        server = create_server(_runtime)
        async with Client(server) as client:
            tools = await client.list_tools()

        assert {tool.name for tool in tools} == {
            "retrieve_context",
            "lookup_vendor",
            "check_budget",
            "flag_duplicate",
            "extract_invoice_data",
        }
        tool = next(tool for tool in tools if tool.name == "retrieve_context")
        assert tool.name == "retrieve_context"
        assert tool.inputSchema["properties"]["mode"]["default"] == "vector"
        assert tool.inputSchema["properties"]["top_k"]["maximum"] == 10
        assert "as_of_date" in tool.inputSchema["properties"]
        assert "include_expired" not in tool.inputSchema["properties"]
        assert "metadata_filter" not in tool.inputSchema["properties"]
        assert "reranker_model_id" not in tool.inputSchema["properties"]
        assert tool.outputSchema is not None
        document_type = tool.outputSchema["properties"]["results"]["items"][
            "properties"
        ]["document"]["properties"]["document_type"]
        assert document_type["enum"] == ["vendor_contract", "spending_policy"]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False

        vendor_tool = next(tool for tool in tools if tool.name == "lookup_vendor")
        assert set(vendor_tool.inputSchema["properties"]) == {"identifier"}
        assert vendor_tool.outputSchema is not None
        vendor_properties = vendor_tool.outputSchema["properties"]["results"][
            "items"
        ]["properties"]["vendor"]["properties"]
        assert "contact" not in vendor_properties
        assert "remittance_profile_ref" not in vendor_properties

        budget_tool = next(tool for tool in tools if tool.name == "check_budget")
        assert set(budget_tool.inputSchema["properties"]) == {"invoice_id"}
        assert "category" not in budget_tool.inputSchema["properties"]
        assert "expected_cost_center" not in budget_tool.inputSchema["properties"]
        assert budget_tool.annotations is not None
        assert budget_tool.annotations.readOnlyHint is True

        duplicate_tool = next(
            tool for tool in tools if tool.name == "flag_duplicate"
        )
        assert set(duplicate_tool.inputSchema["properties"]) == {"invoice_id"}
        assert duplicate_tool.annotations is not None
        assert duplicate_tool.annotations.readOnlyHint is True
        assert duplicate_tool.annotations.destructiveHint is False

        extraction_tool = next(
            tool for tool in tools if tool.name == "extract_invoice_data"
        )
        assert set(extraction_tool.inputSchema["properties"]) == {"invoice_id"}
        assert extraction_tool.annotations is not None
        assert extraction_tool.annotations.readOnlyHint is True
        assert extraction_tool.annotations.openWorldHint is False
        assert extraction_tool.outputSchema is not None
        extracted_fields = extraction_tool.outputSchema["properties"][
            "extracted_invoice"
        ]["anyOf"][0]["properties"]
        assert "record_status" not in extracted_fields
        assert "source_path" not in extracted_fields

    asyncio.run(exercise())


def test_mcp_client_receives_vendor_and_budget_structured_content() -> None:
    async def exercise() -> None:
        server = create_server(_runtime)
        async with Client(server) as client:
            vendor_result = await asyncio.wait_for(
                client.call_tool("lookup_vendor", {"identifier": "CFG Services"}),
                timeout=5,
            )
            budget_result = await asyncio.wait_for(
                client.call_tool(
                    "check_budget",
                    {"invoice_id": "INV-2026-0019"},
                ),
                timeout=5,
            )
            duplicate_result = await asyncio.wait_for(
                client.call_tool(
                    "flag_duplicate",
                    {"invoice_id": "INV-2026-0019"},
                ),
                timeout=5,
            )
            extraction_result = await asyncio.wait_for(
                client.call_tool(
                    "extract_invoice_data",
                    {"invoice_id": "INV-2026-0019"},
                ),
                timeout=5,
            )

        assert vendor_result.is_error is False
        assert vendor_result.structured_content is not None
        assert vendor_result.structured_content["lookup_status"] == "found"
        assert vendor_result.structured_content["results"][0]["vendor"][
            "vendor_id"
        ] == "VND-1007"
        assert budget_result.is_error is False
        assert budget_result.structured_content is not None
        assert budget_result.structured_content["check_status"] == "evaluated"
        assert budget_result.structured_content["evaluation"]["status"] == (
            "budget_exceeded"
        )
        assert budget_result.structured_content["budget"][
            "committed_amount"
        ] == "11400.00"
        assert duplicate_result.is_error is False
        assert duplicate_result.structured_content is not None
        assert duplicate_result.structured_content["finding_status"] == (
            "no_duplicate"
        )
        assert extraction_result.is_error is False
        assert extraction_result.structured_content is not None
        assert extraction_result.structured_content["extraction_status"] == "extracted"
        assert extraction_result.structured_content["extracted_invoice"][
            "total_due"
        ] == "1450.00"

    asyncio.run(exercise())


def test_mcp_client_receives_validated_structured_content() -> None:
    async def exercise() -> None:
        server = create_server(_runtime)
        async with Client(server) as client:
            result = await asyncio.wait_for(
                client.call_tool(
                    "retrieve_context",
                    {
                        "query": "Which approval clause applies?",
                        "mode": "hybrid_reranked",
                        "top_k": 1,
                        "category": "cloud_software",
                        "as_of_date": "2026-07-01",
                    },
                ),
                timeout=5,
            )

        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["mode"] == "hybrid_reranked"
        assert result.structured_content["evidence_status"] == "found"
        assert result.structured_content["filters"]["as_of_date"] == "2026-07-01"
        assert result.structured_content["results"][0]["citation_id"].startswith(
            "POL-CLOUD-2026"
        )
        assert result.content

    asyncio.run(exercise())


@contextmanager
def _runtime() -> Iterator[MCPRuntime]:
    vendor = _vendor()
    invoice = _invoice()
    structured = _tool(
        vendors=StaticVendorRepository(
            by_id={vendor.vendor_id: vendor},
            by_name=(vendor,),
        ),
        budgets=StaticBudgetRepository(_budget()),
        invoices=StaticInvoiceRepository(
            by_id={invoice.invoice_id: invoice},
            committed=Decimal("6400.00"),
        ),
    )
    yield MCPRuntime(
        retrieval=RetrievalTool(StaticService((_result(),))),  # type: ignore[arg-type]
        structured=structured,
        extraction=StaticExtractionTool(),  # type: ignore[arg-type]
    )


class StaticExtractionTool:
    async def extract_invoice_data(self, invoice_id: str) -> ExtractInvoiceResponse:
        return ExtractInvoiceResponse(
            invoice_id=invoice_id,
            extraction_status=InvoiceExtractionStatus.EXTRACTED,
            extracted_invoice=ExtractedInvoice(
                invoice_id=invoice_id,
                vendor_invoice_number="CFG-EM-2026-119",
                vendor_id="VND-1007",
                invoice_date="2026-07-24",
                currency="USD",
                total_due="1450.00",
                lines=(
                    ExtractedInvoiceLine(
                        description="Emergency water-response labor",
                        quantity="10",
                        unit_price="145.00",
                        amount="1450.00",
                    ),
                ),
                payment_terms="NET_30",
                cost_center="FACILITIES",
                po_number="PO-2026-2291",
            ),
            model_id="test-model",
            usage=ModelTokenUsage(
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            ),
        )
