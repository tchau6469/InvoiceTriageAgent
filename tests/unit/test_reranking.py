"""Tests for model-independent cross-encoder reranking."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from invoice_triage.domain import (
    DocumentChunk,
    DocumentType,
    RetrievalQuery,
    SearchResult,
    VendorCategory,
)
from invoice_triage.embeddings import DeterministicEmbeddingClient
from invoice_triage.reranking import (
    AP_RERANK_INSTRUCTION,
    MINILM_RERANKER_MODEL_ID,
    QWEN3_RERANKER_MODEL_ID,
    CrossEncoderRerankerClient,
    rerank_search_results,
)
from invoice_triage.retrieval import RetrievalMode, RetrievalService


class StaticReranker:
    model_id = "test/static-reranker"

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.passages: list[str] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        assert query
        self.passages = passages
        return self._scores


def test_reranking_preserves_prior_scores_and_enriches_passage_text() -> None:
    candidates = (
        _result("a", rank=1, combined=0.04, vector=0.9),
        _result("b", rank=2, combined=0.03, keyword=0.8),
    )
    reranker = StaticReranker([0.1, 0.9])

    results = rerank_search_results(
        "Which clause controls payment?",
        candidates,
        reranker,
        top_k=2,
    )

    assert [result.chunk.chunk_id for result in results] == ["b", "a"]
    assert results[0].keyword_score == 0.8
    assert results[0].combined_score == 0.03
    assert results[0].reranker_score == 0.9
    assert results[0].final_score == 0.9
    assert reranker.passages[0].startswith("Document a\n\nSection a")


def test_cross_encoder_adapter_uses_instruction_only_for_qwen(monkeypatch) -> None:
    constructions: list[tuple[str, dict[str, object]]] = []
    predictions: list[tuple[list[tuple[str, str]], dict[str, object]]] = []

    class FakeScores:
        def tolist(self) -> list[float]:
            return [0.75]

    class FakeCrossEncoder:
        def __init__(self, model_id: str, **kwargs: object) -> None:
            constructions.append((model_id, kwargs))

        def predict(
            self,
            pairs: list[tuple[str, str]],
            **kwargs: object,
        ) -> FakeScores:
            predictions.append((pairs, kwargs))
            return FakeScores()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(CrossEncoder=FakeCrossEncoder),
    )

    qwen = CrossEncoderRerankerClient.for_model(QWEN3_RERANKER_MODEL_ID)
    minilm = CrossEncoderRerankerClient.for_model(MINILM_RERANKER_MODEL_ID)

    assert qwen.score("query", ["passage"]) == [0.75]
    assert minilm.score("query", ["passage"]) == [0.75]
    assert constructions[0][1]["prompts"] == {
        "accounts_payable": AP_RERANK_INSTRUCTION
    }
    assert constructions[0][1]["default_prompt_name"] == "accounts_payable"
    assert "prompts" not in constructions[1][1]
    assert predictions[0][1] == {"batch_size": 4, "show_progress_bar": False}


def test_hybrid_reranking_releases_database_connection_before_model_scoring() -> None:
    database = FakeDatabase()
    reranker = ConnectionCheckingReranker(database)
    service = RetrievalService(
        database,  # type: ignore[arg-type]
        DeterministicEmbeddingClient(dimensions=4),
        rerank_candidates=3,
        reranker_client=reranker,
        vector_searcher=StaticSearcher(
            (_result("a", rank=1, combined=0.9, vector=0.9),)
        ),
        keyword_searcher=StaticSearcher(
            (_result("b", rank=1, combined=0.8, keyword=0.8),)
        ),
    )

    results = service.search_with_embedding(
        RetrievalQuery(query="payment rule", top_k=2),
        mode=RetrievalMode.HYBRID_RERANKED,
        query_embedding=[0.5] * 4,
    )

    assert database.active is False
    assert len(results) == 2
    assert all(result.reranker_score is not None for result in results)


def test_reranking_rejects_wrong_score_count() -> None:
    with pytest.raises(ValueError, match="scores for 1 candidates"):
        rerank_search_results(
            "query",
            (_result("a", rank=1, combined=0.1),),
            StaticReranker([]),
            top_k=1,
        )


class FakeDatabase:
    def __init__(self) -> None:
        self.active = False

    @contextmanager
    def connection(self):
        self.active = True
        try:
            yield object()
        finally:
            self.active = False


class ConnectionCheckingReranker:
    model_id = "test/connection-check"

    def __init__(self, database: FakeDatabase) -> None:
        self._database = database

    def score(self, query: str, passages: list[str]) -> list[float]:
        assert self._database.active is False
        return [float(index) for index in range(len(passages))]


class StaticSearcher:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self._results = results

    def search(self, *args, **kwargs) -> tuple[SearchResult, ...]:
        return self._results


def _result(
    chunk_id: str,
    *,
    rank: int,
    combined: float,
    vector: float | None = None,
    keyword: float | None = None,
) -> SearchResult:
    return SearchResult(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id=f"DOC-{chunk_id}",
            document_type=DocumentType.SPENDING_POLICY,
            section=f"Section {chunk_id}",
            ordinal=rank,
            content=f"Content {chunk_id}",
            source_path=f"fixtures/{chunk_id}.md",
            category=VendorCategory.CLOUD_SOFTWARE,
            metadata={"document_title": f"Document {chunk_id}"},
        ),
        rank=rank,
        combined_score=combined,
        vector_score=vector,
        keyword_score=keyword,
    )
