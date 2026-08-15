"""FastMCP server exposing the invoice-triage tool boundary over stdio."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from invoice_triage.config import AppSettings
from invoice_triage.domain import VendorCategory
from invoice_triage.embeddings import Qwen3EmbeddingClient
from invoice_triage.mcp_server.models import (
    CheckBudgetResponse,
    ExtractInvoiceResponse,
    FlagDuplicateResponse,
    LookupVendorResponse,
    RetrieveContextResponse,
)
from invoice_triage.mcp_server.extraction_tool import (
    InvoiceExtractionTool,
    InvoiceSourceReader,
)
from invoice_triage.mcp_server.retrieval_tool import MCP_MAX_TOP_K, RetrievalTool
from invoice_triage.mcp_server.structured_tools import StructuredDataTools
from invoice_triage.reranking import CrossEncoderRerankerClient
from invoice_triage.reasoning import GeminiReasoningClient
from invoice_triage.retrieval import RetrievalMode, RetrievalService
from invoice_triage.storage import Database


@dataclass(frozen=True)
class MCPRuntime:
    """Process-lifetime dependencies shared by every MCP tool."""

    retrieval: RetrievalTool
    structured: StructuredDataTools
    extraction: InvoiceExtractionTool


RuntimeFactory = Callable[[], AbstractContextManager[MCPRuntime]]


@contextmanager
def production_runtime() -> Iterator[MCPRuntime]:
    """Create shared database and lazy local-model clients for one server process."""

    settings = AppSettings.from_environment()
    if settings.gemini_api_key is None:
        raise RuntimeError(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is required for invoice extraction"
        )
    embedding_client = Qwen3EmbeddingClient(
        model_id=settings.embedding_model_id,
        dimensions=settings.embedding_dimensions,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )
    reranker_client = CrossEncoderRerankerClient.for_model(
        settings.reranker_model_id,
        device=settings.reranker_device,
        batch_size=settings.reranker_batch_size,
        max_length=settings.reranker_max_length,
    )
    with Database.from_settings(settings) as database:
        service = RetrievalService.from_settings(
            database,
            embedding_client,
            settings,
            reranker_client=reranker_client,
        )
        yield MCPRuntime(
            retrieval=RetrievalTool(service),
            structured=StructuredDataTools(database),
            extraction=InvoiceExtractionTool(
                database,
                GeminiReasoningClient(
                    api_key=settings.gemini_api_key.get_secret_value(),
                    model_id=settings.reasoning_model_id,
                ),
                InvoiceSourceReader(
                    settings.invoice_source_root,
                    project_root=Path.cwd(),
                ),
            ),
        )


def create_server(runtime_factory: RuntimeFactory = production_runtime) -> FastMCP:
    """Create a server whose dependencies live for exactly one MCP process."""

    runtime_state: dict[str, MCPRuntime] = {}

    @asynccontextmanager
    async def runtime_lifespan(_server: FastMCP):
        with runtime_factory() as runtime:
            runtime_state["runtime"] = runtime
            try:
                yield {}
            finally:
                runtime_state.clear()

    server = FastMCP(
        name="Invoice Triage MCP",
        instructions=(
            "Read-only accounts-payable tools. Retrieved ranking scores are "
            "diagnostic, not calibrated confidence. An empty result means the "
            "corpus contains insufficient evidence and must not be guessed."
        ),
        lifespan=runtime_lifespan,
    )

    @server.tool(
        name="retrieve_context",
        description=(
            "Retrieve contract and spending-policy evidence. Vector is the "
            "evaluated default; use lexical for exact identifiers, hybrid for "
            "mixed semantic/exact queries, and hybrid_reranked only when the "
            "extra reranking stage is warranted. Pass the invoice or service "
            "date to retrieve terms applicable on that date. Empty results "
            "mean insufficient evidence; do not infer a missing rule."
        ),
        annotations=ToolAnnotations(
            title="Retrieve AP grounding context",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        timeout=120.0,
    )
    async def retrieve_context(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=2000,
                description="Question or exact identifier to retrieve evidence for",
            ),
        ],
        mode: Annotated[
            RetrievalMode,
            Field(description="Explicit retrieval strategy"),
        ] = RetrievalMode.VECTOR,
        top_k: Annotated[
            int,
            Field(
                ge=1,
                le=MCP_MAX_TOP_K,
                description="Maximum grounding passages to return",
            ),
        ] = 5,
        category: Annotated[
            VendorCategory | None,
            Field(description="Optional vendor-category scope"),
        ] = None,
        vendor_id: Annotated[
            str | None,
            Field(min_length=1, description="Optional exact vendor ID scope"),
        ] = None,
        as_of_date: Annotated[
            date | None,
            Field(
                description=(
                    "Invoice or service date used to select applicable document terms"
                )
            ),
        ] = None,
    ) -> RetrieveContextResponse:
        runtime = runtime_state.get("runtime")
        if runtime is None:
            raise RuntimeError("MCP retrieval runtime is unavailable")
        return runtime.retrieval.retrieve_context(
            query,
            mode=mode,
            top_k=top_k,
            category=category,
            vendor_id=vendor_id,
            as_of_date=as_of_date,
        )

    @server.tool(
        name="lookup_vendor",
        description=(
            "Resolve an exact vendor ID, legal name, display name, or alias "
            "against the authoritative vendor master. Stable vendor IDs take "
            "precedence. Inspect lookup_status and do not choose between "
            "ambiguous matches without additional evidence."
        ),
        annotations=ToolAnnotations(
            title="Look up vendor master record",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        timeout=30.0,
    )
    async def lookup_vendor(
        identifier: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Exact vendor ID, legal/display name, or alias",
            ),
        ],
    ) -> LookupVendorResponse:
        runtime = runtime_state.get("runtime")
        if runtime is None:
            raise RuntimeError("MCP structured-data runtime is unavailable")
        return runtime.structured.lookup_vendor(identifier)

    @server.tool(
        name="check_budget",
        description=(
            "Evaluate a candidate invoice against the authoritative monthly "
            "budget. Vendor category and expected cost center are derived from "
            "the vendor master, never supplied by the caller. Missing vendor, "
            "budget, or currency compatibility is reported separately from a "
            "business budget outcome."
        ),
        annotations=ToolAnnotations(
            title="Check monthly invoice budget",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        timeout=30.0,
    )
    async def check_budget(
        invoice_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="Stable ID of the persisted candidate invoice",
            ),
        ],
    ) -> CheckBudgetResponse:
        runtime = runtime_state.get("runtime")
        if runtime is None:
            raise RuntimeError("MCP structured-data runtime is unavailable")
        return runtime.structured.check_budget(invoice_id)

    @server.tool(
        name="flag_duplicate",
        description=(
            "Check one persisted invoice against earlier non-rejected records. "
            "Signals are exact vendor invoice number, same-vendor service "
            "period plus amount, and shared shipment identifiers. A possible "
            "duplicate is a review flag only and never rejects or mutates an invoice."
        ),
        annotations=ToolAnnotations(
            title="Flag possible duplicate invoice",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        timeout=30.0,
    )
    async def flag_duplicate(
        invoice_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="Stable ID of the persisted candidate invoice",
            ),
        ],
    ) -> FlagDuplicateResponse:
        runtime = runtime_state.get("runtime")
        if runtime is None:
            raise RuntimeError("MCP structured-data runtime is unavailable")
        return runtime.structured.flag_duplicate(invoice_id)

    @server.tool(
        name="extract_invoice_data",
        description=(
            "Extract normalized fields from the allowlisted synthetic Markdown "
            "source of one persisted invoice. The caller supplies only the stable "
            "invoice ID; the source path is loaded from PostgreSQL and cannot be "
            "chosen by the model or caller. This tool extracts data only and never "
            "recommends, approves, or mutates payment state."
        ),
        annotations=ToolAnnotations(
            title="Extract persisted invoice data",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        timeout=120.0,
    )
    async def extract_invoice_data(
        invoice_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="Stable ID of the persisted synthetic invoice",
            ),
        ],
    ) -> ExtractInvoiceResponse:
        runtime = runtime_state.get("runtime")
        if runtime is None:
            raise RuntimeError("MCP extraction runtime is unavailable")
        return await runtime.extraction.extract_invoice_data(invoice_id)

    return server


mcp = create_server()


def main() -> None:
    """Run the local MCP server over its default stdio transport."""

    mcp.run()


if __name__ == "__main__":
    main()
