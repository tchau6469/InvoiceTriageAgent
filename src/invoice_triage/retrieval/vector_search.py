"""Filtered pgvector cosine-similarity candidate retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pgvector import Vector
from psycopg import Connection
from psycopg.types.json import Jsonb

from invoice_triage.domain import RetrievalQuery, SearchResult
from invoice_triage.retrieval._mapping import CHUNK_SELECT_COLUMNS, chunk_from_row


class VectorSearcher:
    """Retrieve semantic candidates through the pgvector HNSW index."""

    def search(
        self,
        connection: Connection[dict[str, Any]],
        request: RetrievalQuery,
        query_embedding: Sequence[float],
        *,
        candidate_limit: int,
    ) -> tuple[SearchResult, ...]:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        if not query_embedding:
            raise ValueError("query_embedding cannot be empty")

        # pgvector 0.8 iterative scans continue through the HNSW graph when
        # category/vendor predicates filter initial candidates.
        connection.execute("SET LOCAL hnsw.iterative_scan = strict_order")
        rows = connection.execute(
            f"""
            SELECT
                {CHUNK_SELECT_COLUMNS},
                1 - (embedding <=> %(embedding)s) AS vector_score
            FROM document_chunks
            WHERE embedding IS NOT NULL
              AND (
                    (%(as_of_date)s::DATE IS NULL AND status = 'active')
                    OR (
                        %(as_of_date)s::DATE IS NOT NULL
                        AND status IN ('active', 'expired')
                        AND (
                            effective_date IS NULL
                            OR effective_date <= %(as_of_date)s::DATE
                        )
                        AND (
                            expiration_date IS NULL
                            OR expiration_date >= %(as_of_date)s::DATE
                        )
                    )
              )
              AND (%(category)s::TEXT IS NULL OR category = %(category)s)
              AND (%(vendor_id)s::TEXT IS NULL OR vendor_id = %(vendor_id)s)
              AND metadata @> %(metadata_filter)s
            ORDER BY embedding <=> %(embedding)s
            LIMIT %(candidate_limit)s
            """,
            {
                "embedding": Vector(query_embedding),
                "as_of_date": request.as_of_date,
                "category": request.category.value if request.category else None,
                "vendor_id": request.vendor_id,
                "metadata_filter": Jsonb(request.metadata_filter),
                "candidate_limit": candidate_limit,
            },
        ).fetchall()
        return tuple(
            SearchResult(
                chunk=chunk_from_row(row),
                rank=rank,
                vector_score=float(row["vector_score"]),
                combined_score=float(row["vector_score"]),
            )
            for rank, row in enumerate(rows, start=1)
        )
