# Project scripts

Command-line entry points live here. They remain thin wrappers over importable
application services under `src/invoice_triage/`.

Current commands:

- `load_structured_fixtures.py` validates and transactionally upserts the vendor
  master and monthly budgets.
- `load_invoice_fixtures.py` strictly parses all Markdown invoice transaction
  inputs and atomically upserts normalized invoice records and typed identifiers.
- `ingest_grounding_documents.py` parses the contract and policy Markdown,
  creates heading-aware chunks, embeds them with the configured Qwen model, and
  transactionally upserts documents and chunks into PostgreSQL.
- `search.py` runs one user-supplied query through `vector` (default),
  `lexical`, `hybrid`, or `hybrid_reranked` retrieval. It exposes top-k,
  category, vendor, as-of-date, metadata, reranker-model, and JSON-output flags.
- `evaluate_retrieval.py` embeds the 50 labeled test queries once, benchmarks
  vector, lexical, and RRF hybrid retrieval, and prints aggregate metrics plus
  optional detailed JSON. Passing `--with-reranker` uses the configured MiniLM
  default; `--reranker-model-id` selects a controlled alternative. Both add
  RRF-plus-reranking with cold initialization, steady-state reranker latency,
  total latency, process peak RSS, and challenge slices. `--show-misses` prints
  every result whose relevant section was not ranked first.

All scripts remain thin wrappers over importable application services.
