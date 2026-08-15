# Reranker Comparison — 2026-08-14

This experiment adds a fourth retrieval mode to the 50-query benchmark:

```text
vector top 20 + lexical top 20 -> RRF top 10 -> cross-encoder -> final top 5
```

Both rerankers received the same enriched passages (`document title + section +
content`), candidate set, Qwen query embeddings, PostgreSQL corpus, and labeled
queries. Model inference ran locally on CPU. The Qwen reranker used a tailored
accounts-payable relevance instruction; MiniLM used its native MS MARCO scoring
format.

## Quality and latency

| Mode/model | Recall@5 | MRR@5 | nDCG@5 | Mean rerank ms | Mean total ms | p95 total ms |
|---|---:|---:|---:|---:|---:|---:|
| vector only | 1.000 | 0.990 | 0.993 | — | ~2.5 | ~3.5 |
| hybrid RRF | 1.000 | 0.967 | 0.975 | — | ~2.8 | ~4.1 |
| RRF + Qwen3-Reranker-0.6B | 1.000 | 0.940 | 0.956 | 10,057.06 | 10,059.86 | 12,673.85 |
| RRF + ms-marco-MiniLM-L6-v2 | 1.000 | 0.980 | 0.985 | 63.97 | 66.76 | 96.06 |

The Qwen run observed approximately 3,388 MiB peak process RSS with both the
embedding and reranking models resident. MiniLM observed approximately 1,621
MiB. These are process-level peaks, not isolated model allocations.

Observed model initialization/warm-up was approximately 18.8 seconds for Qwen
and 1.0–3.5 seconds for MiniLM. Hugging Face cache state and filesystem speed
affect this number, so steady-state per-query latency is the more useful local
comparison.

## Challenge slices

MiniLM achieved `1.000` MRR@5 on all five adversarial slices: invoice-number
context, clause IDs, acronyms, vendor aliases, and dollar amounts. It corrected
RRF's invoice-context regression while preserving the clause-ID benefit from
lexical search.

Qwen also corrected the invoice-number and clause-ID slices, but reduced the
acronym slice to `0.875` MRR@5 and introduced additional errors in the original
natural-language queries. Its aggregate quality and CPU latency are both worse
than MiniLM in this experiment.

MiniLM's remaining first-rank misses were:

- `RQ-002` at rank 2, improved from RRF rank 3
- `RQ-030` at rank 2, degraded from RRF rank 1

Vector-only retrieval's only miss was terse clause-ID query `RQ-035` at rank 2.
Therefore, no single current mode dominates every query slice.

## Decision

`cross-encoder/ms-marco-MiniLM-L6-v2` is the preferred experimental reranker
for local CPU development. It materially improves RRF at modest steady-state
cost, while Qwen3-Reranker-0.6B is rejected as the CPU default for this corpus.

Vector-only remains the best aggregate mode (`0.990` MRR@5 versus MiniLM's
`0.980`). Retrieval modes remain explicit; the application should not silently
promote reranking until a broader, multi-relevance evaluation demonstrates a
clear end-to-end benefit. Qwen could be revisited only with GPU hosting and a
new evaluation justification.
