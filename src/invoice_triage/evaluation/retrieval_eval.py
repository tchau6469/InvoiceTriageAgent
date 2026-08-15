"""Labeled vector, lexical, and RRF benchmark orchestration."""

from __future__ import annotations

import json
import resource
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from invoice_triage.config import AppSettings
from invoice_triage.domain import RetrievalQuery, VendorCategory
from invoice_triage.embeddings import EmbeddingClient
from invoice_triage.evaluation.metrics import ndcg_at_k, recall_at_k, reciprocal_rank_at_k
from invoice_triage.reranking import RerankerClient
from invoice_triage.retrieval import RetrievalMode, RetrievalService
from invoice_triage.storage import Database


EVALUATION_K = 5


class QueryDifficulty(StrEnum):
    SEMANTIC = "semantic"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


class RetrievalChallenge(StrEnum):
    INVOICE_NUMBER = "invoice_number"
    CLAUSE_ID = "clause_id"
    ACRONYM = "acronym"
    VENDOR_ALIAS = "vendor_alias"
    DOLLAR_AMOUNT = "dollar_amount"


class RetrievalLabel(BaseModel):
    """One test-only relevance judgment; never exposed to runtime retrieval."""

    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    category: VendorCategory
    expected_doc_id: str = Field(min_length=1)
    expected_section: str = Field(min_length=1)
    difficulty: QueryDifficulty
    as_of_date: date | None = None
    challenge: RetrievalChallenge | None = None
    vendor_id: str | None = Field(default=None, min_length=1)
    source_invoice_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_invoice_challenge(self) -> RetrievalLabel:
        if (
            self.challenge is RetrievalChallenge.INVOICE_NUMBER
            and self.source_invoice_id is None
        ):
            raise ValueError("invoice_number challenge requires source_invoice_id")
        if (
            self.source_invoice_id is not None
            and self.challenge is not RetrievalChallenge.INVOICE_NUMBER
        ):
            raise ValueError("source_invoice_id is only valid for invoice_number challenge")
        return self

    @property
    def relevant_id(self) -> str:
        return f"{self.expected_doc_id}\0{self.expected_section}"


@dataclass(frozen=True)
class QueryMeasurement:
    query_id: str
    difficulty: str
    challenge: str | None
    mode: str
    relevant_rank: int | None
    recall_at_5: float
    reciprocal_rank_at_5: float
    ndcg_at_5: float
    database_latency_ms: float
    reranker_latency_ms: float
    total_latency_ms: float
    returned_results: int


@dataclass(frozen=True)
class ModeSummary:
    mode: str
    queries: int
    recall_at_5: float
    mrr_at_5: float
    ndcg_at_5: float
    mean_database_latency_ms: float
    p50_database_latency_ms: float
    p95_database_latency_ms: float
    mean_reranker_latency_ms: float
    mean_total_latency_ms: float
    p95_total_latency_ms: float


@dataclass(frozen=True)
class ChallengeSummary:
    challenge: str
    mode: str
    queries: int
    recall_at_5: float
    mrr_at_5: float
    ndcg_at_5: float


@dataclass(frozen=True)
class BenchmarkReport:
    embedding_model_id: str
    embedding_dimensions: int
    reranker_model_id: str | None
    query_count: int
    embedding_batch_latency_ms: float
    amortized_embedding_latency_ms: float
    reranker_warmup_latency_ms: float | None
    process_peak_rss_mb: float
    vector_candidates: int
    keyword_candidates: int
    rrf_k: int
    rerank_candidates: int
    summaries: tuple[ModeSummary, ...]
    challenge_summaries: tuple[ChallengeSummary, ...]
    measurements: tuple[QueryMeasurement, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)

    def to_markdown(self) -> str:
        lines = [
            "| Mode | Recall@5 | MRR@5 | nDCG@5 | Mean DB ms | "
            "Mean rerank ms | Mean total ms | p95 total ms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for summary in self.summaries:
            lines.append(
                f"| {summary.mode} | {summary.recall_at_5:.3f} | "
                f"{summary.mrr_at_5:.3f} | {summary.ndcg_at_5:.3f} | "
                f"{summary.mean_database_latency_ms:.2f} | "
                f"{summary.mean_reranker_latency_ms:.2f} | "
                f"{summary.mean_total_latency_ms:.2f} | "
                f"{summary.p95_total_latency_ms:.2f} |"
            )
        lines.extend(
            [
                "",
                f"Qwen query batch: {self.embedding_batch_latency_ms:.2f} ms total; "
                f"{self.amortized_embedding_latency_ms:.2f} ms/query amortized.",
                f"Process peak RSS: {self.process_peak_rss_mb:.2f} MiB.",
            ]
        )
        if self.reranker_model_id is not None:
            lines.extend(
                [
                    f"Reranker: {self.reranker_model_id}",
                    f"Reranker cold load/warm-up: "
                    f"{self.reranker_warmup_latency_ms:.2f} ms.",
                ]
            )
        if self.challenge_summaries:
            lines.extend(
                [
                    "",
                    "| Challenge | Mode | Queries | Recall@5 | MRR@5 | nDCG@5 |",
                    "|---|---|---:|---:|---:|---:|",
                ]
            )
            for summary in self.challenge_summaries:
                lines.append(
                    f"| {summary.challenge} | {summary.mode} | {summary.queries} | "
                    f"{summary.recall_at_5:.3f} | {summary.mrr_at_5:.3f} | "
                    f"{summary.ndcg_at_5:.3f} |"
                )
        return "\n".join(lines)


def read_retrieval_labels(path: Path) -> tuple[RetrievalLabel, ...]:
    """Validate a complete JSONL relevance set and reject duplicate query IDs."""

    labels: list[RetrievalLabel] = []
    query_ids: set[str] = set()
    with path.open(encoding="utf-8") as fixture:
        for line_number, line in enumerate(fixture, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                label = RetrievalLabel.model_validate(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid retrieval label: {exc}") from exc
            if label.query_id in query_ids:
                raise ValueError(f"{path}:{line_number}: duplicate query_id {label.query_id}")
            query_ids.add(label.query_id)
            labels.append(label)
    if not labels:
        raise ValueError(f"{path}: no retrieval labels found")
    return tuple(labels)


def run_retrieval_benchmark(
    database: Database,
    embedding_client: EmbeddingClient,
    settings: AppSettings,
    labels: tuple[RetrievalLabel, ...],
    *,
    reranker_client: RerankerClient | None = None,
) -> BenchmarkReport:
    """Embed once, evaluate independent modes, and preserve per-query results."""

    embedding_started = perf_counter()
    embeddings = embedding_client.embed_queries([label.query for label in labels])
    embedding_batch_ms = (perf_counter() - embedding_started) * 1000
    if len(embeddings) != len(labels):
        raise ValueError("embedding provider did not return one vector per evaluation query")

    timed_reranker = _TimedReranker(reranker_client) if reranker_client else None
    reranker_warmup_ms = None
    if timed_reranker is not None:
        timed_reranker.score(
            labels[0].query,
            ["Warm-up passage for accounts-payable relevance scoring."],
        )
        reranker_warmup_ms = timed_reranker.last_latency_ms

    service = RetrievalService.from_settings(
        database,
        embedding_client,
        settings,
        reranker_client=timed_reranker,
    )
    measurements: list[QueryMeasurement] = []
    modes = [RetrievalMode.VECTOR, RetrievalMode.LEXICAL, RetrievalMode.HYBRID]
    if timed_reranker is not None:
        modes.append(RetrievalMode.HYBRID_RERANKED)
    for label, embedding in zip(labels, embeddings, strict=True):
        request = RetrievalQuery(
            query=label.query,
            top_k=EVALUATION_K,
            category=label.category,
            vendor_id=label.vendor_id,
            as_of_date=label.as_of_date,
        )
        for mode in modes:
            if timed_reranker is not None:
                timed_reranker.last_latency_ms = 0.0
            started = perf_counter()
            results = service.search_with_embedding(
                request,
                mode=mode,
                query_embedding=None if mode is RetrievalMode.LEXICAL else embedding,
            )
            total_latency_ms = (perf_counter() - started) * 1000
            reranker_latency_ms = (
                timed_reranker.last_latency_ms
                if mode is RetrievalMode.HYBRID_RERANKED
                and timed_reranker is not None
                else 0.0
            )
            database_latency_ms = max(total_latency_ms - reranker_latency_ms, 0.0)
            ranked_ids = [
                f"{result.chunk.document_id}\0{result.chunk.section}" for result in results
            ]
            relevant_ids = {label.relevant_id}
            relevant_rank = next(
                (
                    rank
                    for rank, result_id in enumerate(ranked_ids, start=1)
                    if result_id in relevant_ids
                ),
                None,
            )
            measurements.append(
                QueryMeasurement(
                    query_id=label.query_id,
                    difficulty=label.difficulty.value,
                    challenge=label.challenge.value if label.challenge else None,
                    mode=mode.value,
                    relevant_rank=relevant_rank,
                    recall_at_5=recall_at_k(ranked_ids, relevant_ids, k=5),
                    reciprocal_rank_at_5=reciprocal_rank_at_k(
                        ranked_ids, relevant_ids, k=5
                    ),
                    ndcg_at_5=ndcg_at_k(ranked_ids, relevant_ids, k=5),
                    database_latency_ms=database_latency_ms,
                    reranker_latency_ms=reranker_latency_ms,
                    total_latency_ms=total_latency_ms,
                    returned_results=len(results),
                )
            )

    summaries = tuple(_summarize(mode, measurements) for mode in modes)
    challenge_summaries = tuple(
        _summarize_challenge(challenge, mode, measurements)
        for challenge in RetrievalChallenge
        for mode in modes
        if any(
            item.challenge == challenge.value and item.mode == mode.value
            for item in measurements
        )
    )
    return BenchmarkReport(
        embedding_model_id=embedding_client.model_id,
        embedding_dimensions=embedding_client.dimensions,
        reranker_model_id=reranker_client.model_id if reranker_client else None,
        query_count=len(labels),
        embedding_batch_latency_ms=embedding_batch_ms,
        amortized_embedding_latency_ms=embedding_batch_ms / len(labels),
        reranker_warmup_latency_ms=reranker_warmup_ms,
        process_peak_rss_mb=_process_peak_rss_mb(),
        vector_candidates=settings.vector_candidates,
        keyword_candidates=settings.keyword_candidates,
        rrf_k=settings.rrf_k,
        rerank_candidates=settings.rerank_candidates,
        summaries=summaries,
        challenge_summaries=challenge_summaries,
        measurements=tuple(measurements),
    )


def _summarize(
    mode: RetrievalMode,
    measurements: list[QueryMeasurement],
) -> ModeSummary:
    selected = [measurement for measurement in measurements if measurement.mode == mode.value]
    latencies = [measurement.database_latency_ms for measurement in selected]
    reranker_latencies = [measurement.reranker_latency_ms for measurement in selected]
    total_latencies = [measurement.total_latency_ms for measurement in selected]
    return ModeSummary(
        mode=mode.value,
        queries=len(selected),
        recall_at_5=statistics.fmean(item.recall_at_5 for item in selected),
        mrr_at_5=statistics.fmean(item.reciprocal_rank_at_5 for item in selected),
        ndcg_at_5=statistics.fmean(item.ndcg_at_5 for item in selected),
        mean_database_latency_ms=statistics.fmean(latencies),
        p50_database_latency_ms=_percentile(latencies, 0.50),
        p95_database_latency_ms=_percentile(latencies, 0.95),
        mean_reranker_latency_ms=statistics.fmean(reranker_latencies),
        mean_total_latency_ms=statistics.fmean(total_latencies),
        p95_total_latency_ms=_percentile(total_latencies, 0.95),
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summarize_challenge(
    challenge: RetrievalChallenge,
    mode: RetrievalMode,
    measurements: list[QueryMeasurement],
) -> ChallengeSummary:
    selected = [
        item
        for item in measurements
        if item.challenge == challenge.value and item.mode == mode.value
    ]
    return ChallengeSummary(
        challenge=challenge.value,
        mode=mode.value,
        queries=len(selected),
        recall_at_5=statistics.fmean(item.recall_at_5 for item in selected),
        mrr_at_5=statistics.fmean(item.reciprocal_rank_at_5 for item in selected),
        ndcg_at_5=statistics.fmean(item.ndcg_at_5 for item in selected),
    )


class _TimedReranker:
    """Measure model scoring without leaking timing into runtime interfaces."""

    def __init__(self, delegate: RerankerClient) -> None:
        self._delegate = delegate
        self.model_id = delegate.model_id
        self.last_latency_ms = 0.0

    def score(self, query: str, passages: list[str]) -> list[float]:
        started = perf_counter()
        try:
            return self._delegate.score(query, passages)
        finally:
            self.last_latency_ms = (perf_counter() - started) * 1000


def _process_peak_rss_mb() -> float:
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return peak / (1024 * 1024)
    return peak / 1024
