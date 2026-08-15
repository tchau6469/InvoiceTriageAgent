"""Weighted PostgreSQL native full-text candidate retrieval."""

from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoice_triage.domain import RetrievalQuery, SearchResult
from invoice_triage.retrieval._mapping import CHUNK_SELECT_COLUMNS, chunk_from_row


class KeywordSearcher:
    """Retrieve lexical candidates with English normalization and cover density."""

    def search(
        self,
        connection: Connection[dict[str, Any]],
        request: RetrievalQuery,
        *,
        candidate_limit: int,
    ) -> tuple[SearchResult, ...]:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")

        rows = connection.execute(
            f"""
            WITH normalized_lexemes AS (
                SELECT unnest(
                    tsvector_to_array(to_tsvector('english', %(query)s))
                ) AS lexeme
            ),
            query_terms AS (
                SELECT coalesce(
                    string_agg(quote_literal(lexeme), ' | ')::TSQUERY,
                    ''::TSQUERY
                ) AS query
                FROM normalized_lexemes
            )
            SELECT
                {CHUNK_SELECT_COLUMNS},
                ts_rank_cd(search_vector, query_terms.query, 32) AS keyword_score
            FROM document_chunks
            CROSS JOIN query_terms
            WHERE query_terms.query <> ''::TSQUERY
              AND search_vector @@ query_terms.query
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
            ORDER BY keyword_score DESC, chunk_id
            LIMIT %(candidate_limit)s
            """,
            {
                "query": request.query,
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
                keyword_score=float(row["keyword_score"]),
                combined_score=float(row["keyword_score"]),
            )
            for rank, row in enumerate(rows, start=1)
        )
