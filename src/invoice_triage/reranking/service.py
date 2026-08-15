"""Pure reranking policy over provenance-rich retrieval candidates."""

from __future__ import annotations

from collections.abc import Sequence

from invoice_triage.domain import DocumentChunk, SearchResult
from invoice_triage.reranking.client import RerankerClient


def passage_text(chunk: DocumentChunk) -> str:
    """Build the query-passage text seen by a cross-encoder."""

    title = chunk.metadata.get("document_title")
    parts = [title] if isinstance(title, str) and title.strip() else []
    parts.extend((chunk.section, chunk.content))
    return "\n\n".join(parts)


def rerank_search_results(
    query: str,
    candidates: Sequence[SearchResult],
    reranker: RerankerClient,
    *,
    top_k: int,
) -> tuple[SearchResult, ...]:
    """Score candidates jointly and retain every earlier-stage score."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not candidates:
        return ()

    scores = reranker.score(
        query,
        [passage_text(candidate.chunk) for candidate in candidates],
    )
    if len(scores) != len(candidates):
        raise ValueError(
            f"reranker returned {len(scores)} scores for {len(candidates)} candidates"
        )

    ordered = sorted(
        zip(candidates, scores, strict=True),
        key=lambda item: (-item[1], item[0].rank, item[0].chunk.chunk_id),
    )[:top_k]
    return tuple(
        SearchResult(
            chunk=candidate.chunk,
            rank=rank,
            vector_score=candidate.vector_score,
            keyword_score=candidate.keyword_score,
            combined_score=candidate.combined_score,
            reranker_score=score,
        )
        for rank, (candidate, score) in enumerate(ordered, start=1)
    )
