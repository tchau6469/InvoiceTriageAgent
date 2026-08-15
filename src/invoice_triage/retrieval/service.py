"""Application-facing vector, lexical, hybrid, and reranked retrieval service."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from invoice_triage.config import AppSettings
from invoice_triage.domain import RetrievalQuery, SearchResult
from invoice_triage.embeddings import EmbeddingClient
from invoice_triage.reranking import RerankerClient, rerank_search_results
from invoice_triage.retrieval.hybrid_search import reciprocal_rank_fusion
from invoice_triage.retrieval.keyword_search import KeywordSearcher
from invoice_triage.retrieval.vector_search import VectorSearcher
from invoice_triage.storage import Database


class RetrievalMode(StrEnum):
    VECTOR = "vector"
    LEXICAL = "lexical"
    HYBRID = "hybrid"
    HYBRID_RERANKED = "hybrid_reranked"


class RetrievalService:
    """Coordinate query embedding, retrieval, rank fusion, and reranking."""

    def __init__(
        self,
        database: Database,
        embedding_client: EmbeddingClient,
        *,
        vector_candidates: int = 20,
        keyword_candidates: int = 20,
        rrf_k: int = 60,
        rerank_candidates: int = 10,
        reranker_client: RerankerClient | None = None,
        vector_searcher: VectorSearcher | None = None,
        keyword_searcher: KeywordSearcher | None = None,
    ) -> None:
        if vector_candidates < 1 or keyword_candidates < 1:
            raise ValueError("candidate counts must be positive")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if rerank_candidates < 1:
            raise ValueError("rerank_candidates must be positive")
        self._database = database
        self._embedding_client = embedding_client
        self._vector_candidates = vector_candidates
        self._keyword_candidates = keyword_candidates
        self._rrf_k = rrf_k
        self._rerank_candidates = rerank_candidates
        self._reranker_client = reranker_client
        self._vector_searcher = vector_searcher or VectorSearcher()
        self._keyword_searcher = keyword_searcher or KeywordSearcher()

    @classmethod
    def from_settings(
        cls,
        database: Database,
        embedding_client: EmbeddingClient,
        settings: AppSettings,
        *,
        reranker_client: RerankerClient | None = None,
    ) -> RetrievalService:
        return cls(
            database,
            embedding_client,
            vector_candidates=settings.vector_candidates,
            keyword_candidates=settings.keyword_candidates,
            rrf_k=settings.rrf_k,
            rerank_candidates=settings.rerank_candidates,
            reranker_client=reranker_client,
        )

    def search(
        self,
        request: RetrievalQuery,
        *,
        mode: RetrievalMode,
    ) -> tuple[SearchResult, ...]:
        query_embedding = None
        if mode in {
            RetrievalMode.VECTOR,
            RetrievalMode.HYBRID,
            RetrievalMode.HYBRID_RERANKED,
        }:
            query_embedding = self._embedding_client.embed_query(request.query)
        return self.search_with_embedding(
            request,
            mode=mode,
            query_embedding=query_embedding,
        )

    def search_with_embedding(
        self,
        request: RetrievalQuery,
        *,
        mode: RetrievalMode,
        query_embedding: Sequence[float] | None = None,
    ) -> tuple[SearchResult, ...]:
        embedding_modes = {
            RetrievalMode.VECTOR,
            RetrievalMode.HYBRID,
            RetrievalMode.HYBRID_RERANKED,
        }
        if mode in embedding_modes and query_embedding is None:
            raise ValueError(f"{mode.value} retrieval requires a query embedding")
        if mode is RetrievalMode.HYBRID_RERANKED and self._reranker_client is None:
            raise ValueError("hybrid_reranked retrieval requires a reranker client")

        with self._database.connection() as connection:
            if mode is RetrievalMode.LEXICAL:
                results = self._keyword_searcher.search(
                    connection,
                    request,
                    candidate_limit=max(request.top_k, self._keyword_candidates),
                )
                return results[: request.top_k]

            assert query_embedding is not None
            vector_results = self._vector_searcher.search(
                connection,
                request,
                query_embedding,
                candidate_limit=max(request.top_k, self._vector_candidates),
            )
            if mode is RetrievalMode.VECTOR:
                return vector_results[: request.top_k]

            keyword_results = self._keyword_searcher.search(
                connection,
                request,
                candidate_limit=max(request.top_k, self._keyword_candidates),
            )
            fused = reciprocal_rank_fusion(
                vector_results,
                keyword_results,
                top_k=(
                    request.top_k
                    if mode is RetrievalMode.HYBRID
                    else max(request.top_k, self._rerank_candidates)
                ),
                rrf_k=self._rrf_k,
            )

        if mode is RetrievalMode.HYBRID:
            return fused

        assert self._reranker_client is not None
        return rerank_search_results(
            request.query,
            fused,
            self._reranker_client,
            top_k=request.top_k,
        )
