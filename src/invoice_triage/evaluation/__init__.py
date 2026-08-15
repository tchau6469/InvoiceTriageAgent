"""Offline retrieval evaluation and metric calculation."""

from invoice_triage.evaluation.metrics import ndcg_at_k, recall_at_k, reciprocal_rank_at_k
from invoice_triage.evaluation.retrieval_eval import (
    BenchmarkReport,
    ChallengeSummary,
    RetrievalChallenge,
    RetrievalLabel,
    read_retrieval_labels,
    run_retrieval_benchmark,
)

__all__ = [
    "BenchmarkReport",
    "ChallengeSummary",
    "RetrievalChallenge",
    "RetrievalLabel",
    "ndcg_at_k",
    "read_retrieval_labels",
    "recall_at_k",
    "reciprocal_rank_at_k",
    "run_retrieval_benchmark",
]
