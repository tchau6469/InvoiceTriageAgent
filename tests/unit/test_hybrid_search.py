"""Tests for score-independent Reciprocal Rank Fusion."""

from invoice_triage.domain import DocumentChunk, DocumentType, SearchResult, VendorCategory
from invoice_triage.retrieval import reciprocal_rank_fusion


def test_rrf_promotes_chunk_found_by_both_retrievers() -> None:
    vector = (
        _result("a", rank=1, vector_score=0.95),
        _result("b", rank=2, vector_score=0.80),
    )
    lexical = (
        _result("b", rank=1, keyword_score=0.50),
        _result("c", rank=2, keyword_score=0.40),
    )

    fused = reciprocal_rank_fusion(vector, lexical, top_k=3, rrf_k=60)

    assert [result.chunk.chunk_id for result in fused] == ["b", "a", "c"]
    assert [result.rank for result in fused] == [1, 2, 3]
    assert fused[0].vector_score == 0.80
    assert fused[0].keyword_score == 0.50
    assert fused[0].combined_score == (1 / 62) + (1 / 61)


def _result(
    chunk_id: str,
    *,
    rank: int,
    vector_score: float | None = None,
    keyword_score: float | None = None,
) -> SearchResult:
    chunk = DocumentChunk(
        chunk_id=chunk_id,
        document_id=f"DOC-{chunk_id}",
        document_type=DocumentType.SPENDING_POLICY,
        section=f"Section {chunk_id}",
        ordinal=rank,
        content=f"Content for {chunk_id}",
        source_path=f"fixtures/{chunk_id}.md",
        category=VendorCategory.CLOUD_SOFTWARE,
    )
    raw_score = vector_score if vector_score is not None else keyword_score
    assert raw_score is not None
    return SearchResult(
        chunk=chunk,
        rank=rank,
        vector_score=vector_score,
        keyword_score=keyword_score,
        combined_score=raw_score,
    )
