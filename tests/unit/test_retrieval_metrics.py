"""Tests for ranked retrieval evaluation metrics."""

import math

import pytest

from invoice_triage.evaluation.metrics import ndcg_at_k, recall_at_k, reciprocal_rank_at_k


def test_metrics_reward_relevant_item_at_second_rank() -> None:
    ranked = ["wrong", "relevant", "also-wrong"]
    relevant = {"relevant"}

    assert recall_at_k(ranked, relevant, k=5) == 1.0
    assert reciprocal_rank_at_k(ranked, relevant, k=5) == 0.5
    assert ndcg_at_k(ranked, relevant, k=5) == pytest.approx(1 / math.log2(3))


def test_metrics_return_zero_when_relevant_item_is_beyond_cutoff() -> None:
    ranked = ["a", "b", "c", "d", "e", "relevant"]
    relevant = {"relevant"}

    assert recall_at_k(ranked, relevant, k=5) == 0.0
    assert reciprocal_rank_at_k(ranked, relevant, k=5) == 0.0
    assert ndcg_at_k(ranked, relevant, k=5) == 0.0


def test_metrics_reject_empty_relevance_set() -> None:
    with pytest.raises(ValueError, match="relevant_ids cannot be empty"):
        recall_at_k(["a"], set(), k=5)
