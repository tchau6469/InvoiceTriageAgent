"""Adapter from the public MCP contract to the retrieval service."""

from __future__ import annotations

from datetime import date

from invoice_triage.domain import RetrievalQuery, SearchResult, VendorCategory
from invoice_triage.mcp_server.models import (
    AppliedRetrievalFilters,
    EvidenceDocument,
    EvidenceStatus,
    GroundingDocumentType,
    RetrievalEvidence,
    RetrievalScores,
    RetrieveContextResponse,
)
from invoice_triage.retrieval import RetrievalMode, RetrievalService


MCP_MAX_TOP_K = 10


class RetrievalTool:
    """Expose allowlisted retrieval evidence without generation or side effects."""

    def __init__(self, service: RetrievalService) -> None:
        self._service = service

    def retrieve_context(
        self,
        query: str,
        *,
        mode: RetrievalMode = RetrievalMode.VECTOR,
        top_k: int = 5,
        category: VendorCategory | None = None,
        vendor_id: str | None = None,
        as_of_date: date | None = None,
    ) -> RetrieveContextResponse:
        if not query.strip():
            raise ValueError("query cannot be empty")
        if not 1 <= top_k <= MCP_MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {MCP_MAX_TOP_K}")

        request = RetrievalQuery(
            query=query,
            top_k=top_k,
            category=category,
            vendor_id=vendor_id,
            as_of_date=as_of_date,
        )
        results = self._service.search(request, mode=mode)
        evidence = tuple(_evidence_from_result(result, mode) for result in results)
        return RetrieveContextResponse(
            query=request.query,
            mode=mode,
            filters=AppliedRetrievalFilters(
                category=request.category,
                vendor_id=request.vendor_id,
                as_of_date=request.as_of_date,
            ),
            evidence_status=(
                EvidenceStatus.FOUND if evidence else EvidenceStatus.NOT_FOUND
            ),
            result_count=len(evidence),
            results=evidence,
        )


def _evidence_from_result(
    result: SearchResult,
    mode: RetrievalMode,
) -> RetrievalEvidence:
    chunk = result.chunk
    return RetrievalEvidence(
        citation_id=chunk.chunk_id,
        rank=result.rank,
        content=chunk.content,
        document=EvidenceDocument(
            document_id=chunk.document_id,
            document_type=GroundingDocumentType(chunk.document_type.value),
            title=str(chunk.metadata.get("document_title", chunk.document_id)),
            section=chunk.section,
            source_path=chunk.source_path,
            status=chunk.status,
            vendor_id=chunk.vendor_id,
            category=chunk.category,
            effective_date=chunk.effective_date,
            expiration_date=chunk.expiration_date,
        ),
        scores=RetrievalScores(
            final=result.final_score,
            vector=result.vector_score,
            lexical=result.keyword_score,
            rrf=(
                result.combined_score
                if mode in {RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANKED}
                else None
            ),
            reranker=result.reranker_score,
        ),
    )
