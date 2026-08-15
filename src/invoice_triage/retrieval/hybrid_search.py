"""Reciprocal Rank Fusion over independently ranked candidate lists."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from invoice_triage.domain import SearchResult


@dataclass
class _FusedCandidate:
    result: SearchResult
    score: float = 0.0
    vector_score: float | None = None
    keyword_score: float | None = None


def reciprocal_rank_fusion(
    vector_results: Sequence[SearchResult],
    keyword_results: Sequence[SearchResult],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> tuple[SearchResult, ...]:
    """Fuse ranks without attempting to calibrate incomparable raw scores."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")

    candidates: dict[str, _FusedCandidate] = {}
    for result in vector_results:
        candidate = candidates.setdefault(
            result.chunk.chunk_id,
            _FusedCandidate(result=result),
        )
        candidate.score += 1.0 / (rrf_k + result.rank)
        candidate.vector_score = result.vector_score

    for result in keyword_results:
        candidate = candidates.setdefault(
            result.chunk.chunk_id,
            _FusedCandidate(result=result),
        )
        candidate.score += 1.0 / (rrf_k + result.rank)
        candidate.keyword_score = result.keyword_score

    ordered = sorted(
        candidates.values(),
        key=lambda candidate: (
            -candidate.score,
            candidate.result.chunk.chunk_id,
        ),
    )[:top_k]
    return tuple(
        SearchResult(
            chunk=candidate.result.chunk,
            rank=rank,
            vector_score=candidate.vector_score,
            keyword_score=candidate.keyword_score,
            combined_score=candidate.score,
        )
        for rank, candidate in enumerate(ordered, start=1)
    )
