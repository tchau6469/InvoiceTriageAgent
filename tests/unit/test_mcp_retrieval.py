"""Tests for the allowlisted MCP retrieval adapter."""

from __future__ import annotations

from datetime import date

import pytest

from invoice_triage.domain import (
    DocumentChunk,
    DocumentType,
    RetrievalQuery,
    SearchResult,
    VendorCategory,
)
from invoice_triage.mcp_server import EvidenceStatus, RetrievalTool
from invoice_triage.retrieval import RetrievalMode


def test_retrieval_tool_maps_filters_provenance_and_all_stage_scores() -> None:
    service = StaticService((_result(),))
    tool = RetrievalTool(service)  # type: ignore[arg-type]

    response = tool.retrieve_context(
        "Which approval clause applies?",
        mode=RetrievalMode.HYBRID_RERANKED,
        top_k=3,
        category=VendorCategory.CLOUD_SOFTWARE,
        vendor_id="VND-1001",
        as_of_date=date(2026, 7, 1),
    )

    assert service.request == RetrievalQuery(
        query="Which approval clause applies?",
        top_k=3,
        category=VendorCategory.CLOUD_SOFTWARE,
        vendor_id="VND-1001",
        as_of_date=date(2026, 7, 1),
    )
    assert service.mode is RetrievalMode.HYBRID_RERANKED
    assert response.evidence_status is EvidenceStatus.FOUND
    assert response.result_count == 1
    assert response.results[0].citation_id == "POL-CLOUD-2026:csp-02"
    assert response.results[0].document.title == "Cloud Software Policy"
    assert response.results[0].document.document_type.value == "spending_policy"
    assert response.results[0].scores.final == 0.95
    assert response.results[0].scores.vector == 0.8
    assert response.results[0].scores.lexical == 0.7
    assert response.results[0].scores.rrf == 0.03
    assert response.results[0].scores.reranker == 0.95
    payload = response.model_dump(mode="json")
    assert "metadata" not in payload["results"][0]["document"]


def test_retrieval_tool_returns_successful_not_found_response() -> None:
    response = RetrievalTool(StaticService(())).retrieve_context(  # type: ignore[arg-type]
        "No matching rule",
        mode=RetrievalMode.VECTOR,
    )

    assert response.evidence_status is EvidenceStatus.NOT_FOUND
    assert response.result_count == 0
    assert response.results == ()


@pytest.mark.parametrize("top_k", [0, 11])
def test_retrieval_tool_enforces_mcp_context_limit(top_k: int) -> None:
    with pytest.raises(ValueError, match="top_k must be between 1 and 10"):
        RetrievalTool(StaticService(())).retrieve_context(  # type: ignore[arg-type]
            "query",
            top_k=top_k,
        )


class StaticService:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self._results = results
        self.request: RetrievalQuery | None = None
        self.mode: RetrievalMode | None = None

    def search(
        self,
        request: RetrievalQuery,
        *,
        mode: RetrievalMode,
    ) -> tuple[SearchResult, ...]:
        self.request = request
        self.mode = mode
        return self._results


def _result() -> SearchResult:
    return SearchResult(
        chunk=DocumentChunk(
            chunk_id="POL-CLOUD-2026:csp-02",
            document_id="POL-CLOUD-2026",
            document_type=DocumentType.SPENDING_POLICY,
            section="CSP-02",
            ordinal=1,
            content="Subscriptions over $10,000 require approval.",
            source_path="fixtures/policies/cloud_software.md",
            category=VendorCategory.CLOUD_SOFTWARE,
            effective_date=date(2026, 1, 1),
            metadata={
                "document_title": "Cloud Software Policy",
                "embedding_model_id": "internal/model-detail",
            },
        ),
        rank=1,
        combined_score=0.03,
        vector_score=0.8,
        keyword_score=0.7,
        reranker_score=0.95,
    )

