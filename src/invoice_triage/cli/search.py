"""Run one grounding-document query through an explicit retrieval mode."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from invoice_triage.config import AppSettings
from invoice_triage.domain import RetrievalQuery, SearchResult, VendorCategory
from invoice_triage.embeddings import Qwen3EmbeddingClient
from invoice_triage.reranking import CrossEncoderRerankerClient
from invoice_triage.retrieval import RetrievalMode, RetrievalService
from invoice_triage.storage import Database


def build_parser() -> argparse.ArgumentParser:
    """Build the stable shell interface without loading models or configuration."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="natural-language or exact-match query")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RetrievalMode],
        default=RetrievalMode.VECTOR.value,
        help="retrieval strategy (default: vector)",
    )
    parser.add_argument(
        "--top-k",
        type=_top_k,
        default=None,
        help="number of results, 1-100 (default: configured retrieval top-k)",
    )
    parser.add_argument(
        "--category",
        choices=[category.value for category in VendorCategory],
        help="limit results to one vendor category",
    )
    parser.add_argument("--vendor-id", help="limit results to one vendor ID")
    parser.add_argument(
        "--as-of-date",
        type=_iso_date,
        metavar="YYYY-MM-DD",
        help="retrieve documents applicable on this invoice or service date",
    )
    parser.add_argument(
        "--metadata-filter",
        type=_json_object,
        default=None,
        metavar="JSON",
        help="JSON object matched against chunk metadata",
    )
    parser.add_argument(
        "--reranker-model-id",
        help=(
            "override the configured reranker model; valid only with "
            "--mode hybrid_reranked"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON response",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse a single query, execute retrieval, and print its ranked evidence."""

    parser = build_parser()
    args = parser.parse_args(argv)
    mode = RetrievalMode(args.mode)
    if args.reranker_model_id and mode is not RetrievalMode.HYBRID_RERANKED:
        parser.error("--reranker-model-id requires --mode hybrid_reranked")

    settings = AppSettings.from_environment()
    request = RetrievalQuery(
        query=args.query,
        top_k=args.top_k or settings.retrieval_top_k,
        category=VendorCategory(args.category) if args.category else None,
        vendor_id=args.vendor_id,
        as_of_date=args.as_of_date,
        metadata_filter=args.metadata_filter or {},
    )
    embedding_client = Qwen3EmbeddingClient(
        model_id=settings.embedding_model_id,
        dimensions=settings.embedding_dimensions,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )
    reranker_client = None
    if mode is RetrievalMode.HYBRID_RERANKED:
        reranker_client = CrossEncoderRerankerClient.for_model(
            args.reranker_model_id or settings.reranker_model_id,
            device=settings.reranker_device,
            batch_size=settings.reranker_batch_size,
            max_length=settings.reranker_max_length,
        )

    with Database.from_settings(settings) as database:
        service = RetrievalService.from_settings(
            database,
            embedding_client,
            settings,
            reranker_client=reranker_client,
        )
        results = service.search(request, mode=mode)

    if args.json:
        print(_render_json(request, mode, results))
    else:
        print(_render_text(request, mode, results))
    return 0


def _top_k(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= value <= 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return value


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return value


def _iso_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a valid ISO date (YYYY-MM-DD)") from exc


def _render_json(
    request: RetrievalQuery,
    mode: RetrievalMode,
    results: Sequence[SearchResult],
) -> str:
    payload = {
        "query": request.model_dump(mode="json"),
        "mode": mode.value,
        "result_count": len(results),
        "results": [result.model_dump(mode="json") for result in results],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _render_text(
    request: RetrievalQuery,
    mode: RetrievalMode,
    results: Sequence[SearchResult],
) -> str:
    lines = [
        f"Query: {request.query}",
        f"Mode: {mode.value}",
        f"Results: {len(results)}",
    ]
    if not results:
        lines.extend(["", "No matching grounding documents found."])
        return "\n".join(lines)

    for result in results:
        chunk = result.chunk
        title = str(chunk.metadata.get("document_title", chunk.document_id))
        scope = []
        if chunk.vendor_id:
            scope.append(f"vendor={chunk.vendor_id}")
        if chunk.category:
            scope.append(f"category={chunk.category.value}")
        scores = [f"final={result.final_score:.6f}"]
        if mode in {RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANKED}:
            scores.append(f"rrf={result.combined_score:.6f}")
        if result.vector_score is not None:
            scores.append(f"vector={result.vector_score:.6f}")
        if result.keyword_score is not None:
            scores.append(f"lexical={result.keyword_score:.6f}")
        if result.reranker_score is not None:
            scores.append(f"reranker={result.reranker_score:.6f}")

        lines.extend(
            [
                "",
                f"[{result.rank}] {title} — {chunk.section}",
                f"    document: {chunk.document_id}",
                f"    source: {chunk.source_path}",
                f"    status: {chunk.status.value}",
                f"    scores: {', '.join(scores)}",
            ]
        )
        if scope:
            lines.append(f"    scope: {', '.join(scope)}")
        lines.extend(["", chunk.content])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
