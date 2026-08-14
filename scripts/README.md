# Project scripts

Command-line entry points live here. They remain thin wrappers over importable
application services under `src/invoice_triage/`.

Current commands:

- `load_structured_fixtures.py` validates and transactionally upserts the vendor
  master and monthly budgets.
- `ingest_grounding_documents.py` parses the contract and policy Markdown,
  creates heading-aware chunks, embeds them with the configured Qwen model, and
  transactionally upserts documents and chunks into PostgreSQL.

A retrieval-evaluation runner remains planned.
