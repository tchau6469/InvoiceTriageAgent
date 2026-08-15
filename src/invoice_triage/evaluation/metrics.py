"""Dependency-free ranked-retrieval metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence, Set


def recall_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Set[str],
    *,
    k: int,
) -> float:
    """Return the fraction of relevant items present in the first k results."""

    _validate_inputs(relevant_ids, k)
    retrieved = set(ranked_ids[:k])
    return len(retrieved & relevant_ids) / len(relevant_ids)


def reciprocal_rank_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Set[str],
    *,
    k: int,
) -> float:
    """Return reciprocal rank of the first relevant result, capped at k."""

    _validate_inputs(relevant_ids, k)
    for rank, item_id in enumerate(ranked_ids[:k], start=1):
        if item_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Set[str],
    *,
    k: int,
) -> float:
    """Return binary normalized discounted cumulative gain at k."""

    _validate_inputs(relevant_ids, k)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item_id in enumerate(ranked_ids[:k], start=1)
        if item_id in relevant_ids
    )
    ideal_count = min(len(relevant_ids), k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal_dcg


def _validate_inputs(relevant_ids: Set[str], k: int) -> None:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant_ids:
        raise ValueError("relevant_ids cannot be empty")
