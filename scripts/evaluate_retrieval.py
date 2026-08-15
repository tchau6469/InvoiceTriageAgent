"""Benchmark vector, lexical, RRF, and optional reranked retrieval."""

from __future__ import annotations

import argparse
from pathlib import Path

from invoice_triage.config import AppSettings
from invoice_triage.embeddings import Qwen3EmbeddingClient
from invoice_triage.evaluation import read_retrieval_labels, run_retrieval_benchmark
from invoice_triage.reranking import CrossEncoderRerankerClient
from invoice_triage.storage import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("fixtures/evaluation/retrieval_queries.jsonl"),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the detailed machine-readable report after the summary",
    )
    reranker_group = parser.add_mutually_exclusive_group()
    reranker_group.add_argument(
        "--with-reranker",
        action="store_true",
        help="evaluate the reranker configured by INVOICE_TRIAGE_RERANKER_MODEL_ID",
    )
    reranker_group.add_argument(
        "--reranker-model-id",
        help="also evaluate hybrid RRF plus this Sentence Transformers reranker",
    )
    parser.add_argument(
        "--show-misses",
        action="store_true",
        help="print measurements whose relevant section was not ranked first",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = read_retrieval_labels(args.labels)
    settings = AppSettings.from_environment()
    embedding_client = Qwen3EmbeddingClient(
        model_id=settings.embedding_model_id,
        dimensions=settings.embedding_dimensions,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )
    reranker_client = None
    reranker_model_id = (
        args.reranker_model_id
        if args.reranker_model_id
        else settings.reranker_model_id if args.with_reranker else None
    )
    if reranker_model_id:
        reranker_client = CrossEncoderRerankerClient.for_model(
            reranker_model_id,
            device=settings.reranker_device,
            batch_size=settings.reranker_batch_size,
            max_length=settings.reranker_max_length,
        )
    with Database.from_settings(settings) as database:
        report = run_retrieval_benchmark(
            database,
            embedding_client,
            settings,
            labels,
            reranker_client=reranker_client,
        )
    print(report.to_markdown())
    if args.show_misses:
        misses = [
            measurement
            for measurement in report.measurements
            if measurement.relevant_rank != 1
        ]
        if misses:
            print()
            print("| Query | Mode | Relevant rank |")
            print("|---|---|---:|")
            for measurement in misses:
                rank = measurement.relevant_rank or "not in top 5"
                print(f"| {measurement.query_id} | {measurement.mode} | {rank} |")
    if args.json:
        print()
        print(report.to_json())


if __name__ == "__main__":
    main()
