# Retrieval Baseline — 2026-08-14

This report records both the original baseline and the expanded adversarial
evaluation for the 195-chunk synthetic contracts and policies corpus. It
compares each retrieval branch independently before combining their ranks with
Reciprocal Rank Fusion (RRF).

## Method

- 50 test-only labeled queries from `fixtures/evaluation/retrieval_queries.jsonl`
- 30 natural-language baseline cases and 20 adversarial exact-match cases
- four adversarial cases each for invoice numbers, clause IDs, acronyms,
  vendor aliases, and dollar amounts
- one relevant document section per query
- category, vendor, and document-lifecycle filters applied equally to every mode
- top 5 results evaluated from 20 vector and 20 lexical candidates
- pgvector cosine distance for semantic retrieval
- PostgreSQL English `tsvector` with `ts_rank_cd(..., 32)` for lexical ranking
- unweighted RRF with `k = 60`; raw vector and lexical scores are not mixed
- Qwen3-Embedding-0.6B query embeddings, 1024 dimensions, CPU execution

## Original 30-query baseline

| Mode | Recall@5 | MRR@5 | nDCG@5 | Mean DB ms | p50 DB ms | p95 DB ms |
|---|---:|---:|---:|---:|---:|---:|
| vector | 1.000 | 1.000 | 1.000 | 2.16 | 1.86 | 4.08 |
| lexical | 1.000 | 0.957 | 0.967 | 2.07 | 1.80 | 3.91 |
| hybrid RRF | 1.000 | 0.961 | 0.971 | 3.50 | 3.26 | 5.40 |

## Expanded 50-query results

| Mode | Recall@5 | MRR@5 | nDCG@5 | Mean DB ms | p50 DB ms | p95 DB ms |
|---|---:|---:|---:|---:|---:|---:|
| vector | 1.000 | 0.990 | 0.993 | 1.73 | 1.72 | 2.28 |
| lexical | 1.000 | 0.964 | 0.973 | 1.48 | 1.37 | 2.39 |
| hybrid RRF | 1.000 | 0.967 | 0.975 | 2.58 | 2.50 | 3.59 |

The 50 query embeddings took 26,236 ms as one CPU batch, or approximately
525 ms per query when amortized. These embedding and database timings are local
development measurements, not production service-level objectives.

## Adversarial slices

| Challenge | Mode | Queries | Recall@5 | MRR@5 | nDCG@5 |
|---|---|---:|---:|---:|---:|
| invoice number | vector | 4 | 1.000 | 1.000 | 1.000 |
| invoice number | lexical | 4 | 1.000 | 0.875 | 0.908 |
| invoice number | hybrid RRF | 4 | 1.000 | 0.875 | 0.908 |
| clause ID | vector | 4 | 1.000 | 0.875 | 0.908 |
| clause ID | lexical | 4 | 1.000 | 1.000 | 1.000 |
| clause ID | hybrid RRF | 4 | 1.000 | 1.000 | 1.000 |
| acronym | vector | 4 | 1.000 | 1.000 | 1.000 |
| acronym | lexical | 4 | 1.000 | 1.000 | 1.000 |
| acronym | hybrid RRF | 4 | 1.000 | 1.000 | 1.000 |
| vendor alias | vector | 4 | 1.000 | 1.000 | 1.000 |
| vendor alias | lexical | 4 | 1.000 | 1.000 | 1.000 |
| vendor alias | hybrid RRF | 4 | 1.000 | 1.000 | 1.000 |
| dollar amount | vector | 4 | 1.000 | 1.000 | 1.000 |
| dollar amount | lexical | 4 | 1.000 | 1.000 | 1.000 |
| dollar amount | hybrid RRF | 4 | 1.000 | 1.000 | 1.000 |

## Interpretation

The adversarial set demonstrates a real lexical contribution. Terse clause IDs
reduce vector MRR@5 to `0.875`, while lexical search and RRF both rank all four
correctly at `1.000`. Acronyms, vendor-alias scenarios, and dollar amounts are
perfect across all modes.

The first clause-ID run also exposed a parser defect: PostgreSQL normalizes
`CSP-05` into `csp` and `-05`, but `websearch_to_tsquery` treats the hyphenated
number as logical NOT. The lexical query builder now quotes normalized lexemes
before constructing an OR `tsquery`, preserving `-05` as an identifier. A live
integration test covers this case.

Invoice numbers behave differently by design. Invoice documents are structured
transaction inputs and never enter the RAG index. Their labels therefore model
the real pipeline: structured lookup supplies vendor/category filters and the
query asks for relevant contract grounding. Vector search handles that natural
language intent better than lexical search; copying invoice identifiers into
the grounding corpus merely to improve this slice would violate the ingestion
boundary.

Overall, vector search remains strongest at `0.990` MRR@5. RRF fixes the
clause-ID weakness but inherits lexical ranking errors in several natural
language and invoice-context queries, producing `0.967` MRR@5. This supports
keeping the modes explicit and testing a reranker instead of claiming that RRF
is automatically superior.

The service therefore requires callers to select `vector`, `lexical`, or
`hybrid` explicitly; it does not silently make RRF the default.

The cross-encoder experiment is recorded separately in
[`reranker_comparison.md`](reranker_comparison.md). MiniLM improves RRF at
modest CPU latency, while Qwen3-Reranker-0.6B is slower and less accurate on
this corpus; vector-only remains the strongest aggregate mode.
