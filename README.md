# AP Invoice Triage Agent

A portfolio implementation of a human-reviewed accounts-payable triage agent
with custom hybrid retrieval. The agent extracts invoice data, checks vendors
and budgets, detects anomalies, retrieves contractual context, and drafts a
recommendation. It never approves or issues payment.

The locked project scope is documented in
`ai_solutions_engineer_project_spec.md`. Synthetic development data and retrieval
evaluation labels live under `fixtures/`.

## Current milestone

The database foundation, structured vendor/budget/invoice loaders, RAG document
ingestion pipeline, retrieval benchmark, single-query CLI, first five MCP
tools, provider-neutral reasoning boundary, Gemini adapter, and LangGraph state
contract are complete. The 24 contract and policy Markdown sources produce 195
heading-aware chunks embedded by Qwen3-Embedding-0.6B and stored in PostgreSQL.
The retrieval layer supports pgvector cosine search, PostgreSQL native full-text
search, and Reciprocal Rank Fusion (RRF) as independently selectable modes. An
experimental fourth mode reranks RRF's top 10 with a model-independent
cross-encoder adapter.

## Local validation

The repository currently requires Python 3.12 or 3.13.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

Local Qwen inference additionally requires the optional embedding dependencies.
Direct Gemini reasoning requires the separate reasoning extra:

```bash
python -m pip install -e ".[embeddings]"
python -m pip install -e ".[reasoning]"
```

Host-side tests skip the PostgreSQL integration suite unless explicitly
enabled. The Compose test command below is the recommended complete check.

## Local PostgreSQL and pgvector

Copy the environment template and replace both password placeholders before
starting the database:

```bash
cp .env.example .env
docker compose up -d postgres
docker compose ps
```

The local image pins PostgreSQL 17 and pgvector 0.8.2. The `vector` extension is
enabled when a new database volume is initialized. Stop the service without
deleting its data with:

```bash
docker compose down
```

Deleting the named database volume is intentionally a separate, destructive
operation and is not part of normal teardown.

To build the application test image and run tests after PostgreSQL is healthy:

```bash
docker compose --profile test run --rm test
```

This command applies all Alembic migrations before running unit and PostgreSQL
integration tests. To apply migrations without running the test suite:

```bash
docker compose --profile tools run --rm migrate
```

Load or refresh the structured vendor and budget fixtures with:

```bash
docker compose --profile tools run --rm load-fixtures
```

The loader validates both complete CSV files before opening a transaction, then
upserts vendors and budgets atomically. It is safe to run repeatedly: vendor IDs
and monthly budget business keys are updated rather than duplicated.

Apply migrations and load the vendor, budget, and normalized invoice fixtures
in dependency order with:

```bash
docker compose --profile tools run --build --rm load-invoices
```

The invoice loader strictly parses the 20 Markdown transaction inputs before
opening a database transaction, then idempotently upserts 12 prior `committed`
records and 8 `pending_review` candidates plus their typed shipment and PO
identifiers. These invoices remain outside the RAG index.

Parse, chunk, embed, and upsert the 18 contracts and 6 policies with:

```bash
docker compose --profile tools run --build --rm ingest-documents
```

The ingestion image installs CPU-only PyTorch and runs as a non-root user. The
first invocation downloads the public Qwen model into the persistent
`huggingface-cache` volume; subsequent invocations reuse it. No Hugging Face API
key is required for this public model, though anonymous Hub rate limits apply.
The pipeline deliberately discovers only `fixtures/contracts/` and
`fixtures/policies/`; invoices and evaluation labels cannot enter the retrieval
index through this command.

Run one query against the ingested grounding corpus with vector retrieval (the
measured default):

```bash
docker compose --profile tools run --build --rm search \
  "What approval is required for cloud software purchases?"
```

Select another retrieval mode explicitly:

```bash
docker compose --profile tools run --rm search \
  "Explain clause CSP-05" --mode lexical

docker compose --profile tools run --rm search \
  "What approval is required for cloud software purchases?" --mode hybrid

docker compose --profile tools run --rm search \
  "What approval is required for cloud software purchases?" \
  --mode hybrid_reranked
```

The supported modes are `vector`, `lexical`, `hybrid`, and
`hybrid_reranked`. The CLI also accepts `--top-k`, `--category`, `--vendor-id`,
`--as-of-date`, `--metadata-filter`, `--reranker-model-id`, and `--json`.
`--reranker-model-id` is valid only with `hybrid_reranked`. Host environments
with the project and embedding dependencies installed can use the equivalent
`invoice-triage-search` console command or `python scripts/search.py`.

## MCP tools

The read-only FastMCP server exposes five tools over stdio:

- `lookup_vendor` resolves an exact vendor ID, legal/display name, or alias and
  returns allowlisted operational vendor-master fields.
- `check_budget` loads a persisted candidate by invoice ID, derives all check
  inputs from that record and the vendor master, and projects it against the
  base budget snapshot plus persisted committed invoices.
- `flag_duplicate` compares a persisted candidate with earlier active records
  using exact vendor invoice numbers, same-vendor service-period/amount pairs,
  and shared shipment identifiers.
- `retrieve_context` calls the evaluated retrieval service in vector, lexical,
  hybrid, or reranked mode and returns grounding passages with provenance.
- `extract_invoice_data` resolves a persisted invoice ID to its allowlisted
  synthetic Markdown source, asks Gemini for strict structured output, validates
  that output against the invoice domain model, and reports provider token use.

The retrieval tool caps `top_k` at 10 and deliberately excludes arbitrary
metadata filters and model identifiers. Vendor responses exclude contact and
remittance details. All five tools are read-only and report missing or
ambiguous prerequisites instead of guessing.

`extract_invoice_data` accepts only `invoice_id`; callers and the model cannot
choose a filesystem path. Source access is restricted to
`fixtures/invoices/*.md`, and traversal, absolute paths, non-Markdown files,
oversized inputs, and model-returned invoice-ID mismatches are rejected. The
Gemini free tier should be used only with this synthetic corpus.

Build the local MCP image once:

```bash
docker compose --profile mcp build mcp-server
```

Configure the hosted reasoning fields in `.env` before using extraction:

```dotenv
INVOICE_TRIAGE_REASONING_PROVIDER=gemini
INVOICE_TRIAGE_REASONING_MODEL_ID=gemini-3.5-flash
INVOICE_TRIAGE_INVOICE_SOURCE_ROOT=fixtures/invoices
GEMINI_API_KEY=<your Google AI Studio key>
```

Compose injects the key into the MCP container; application code never loads
or prints `.env`. The remaining four tools are deterministic/local, but the MCP
runtime currently requires the key at startup because extraction is part of the
same server.

An MCP client should launch the server as a subprocess with this command from
the repository root:

```bash
docker compose --profile mcp run --rm -T mcp-server
```

The process communicates only through MCP messages on standard input/output;
it is expected to wait when started directly. A host environment can instead
run `invoice-triage-mcp` after installing `.[embeddings,mcp,reasoning]`.

`retrieve_context` accepts `query`, `mode`, `top_k`, `category`, `vendor_id`,
and `as_of_date`. Supplying an invoice or service date retrieves active or
expired documents only when that date falls within their effective range.
Without a date, retrieval remains active-only. An empty successful response has
`evidence_status: "not_found"`; database or model failures remain tool errors
and never silently become empty evidence.

`lookup_vendor` accepts one `identifier`. Stable vendor IDs take precedence;
otherwise the lookup uses exact case-insensitive legal name, display name, and
alias matching. Its `lookup_status` is `found`, `not_found`, or `ambiguous`.

`check_budget` accepts only `invoice_id`; vendor, period, cost center, amount,
and currency are read from persisted records rather than caller-supplied. Its
`check_status` separates successful evaluation from `invoice_not_found`,
`vendor_not_found`, `budget_not_found`, and `currency_mismatch`. An evaluated
response reports `within_budget`, `budget_exceeded`, or
`cost_center_mismatch`. The effective committed amount is the base
`monthly_budgets.committed_amount` snapshot plus matching persisted invoices in
`committed` status; the current pending candidate is projected but not counted
twice.

`flag_duplicate` also accepts only `invoice_id`. It reports
`possible_duplicate` with earlier matching records and exact reason codes, or
`no_duplicate`. Purchase-order reuse is retained as evidence but is not, by
itself, treated as proof of a duplicate shipment. The tool never changes an
invoice status; every finding is a human-review flag.

Evaluate vector, lexical, and RRF retrieval against the 50 test-only relevance
labels with:

```bash
docker compose --profile tools run --build --rm evaluate-retrieval
```

The runner embeds all evaluation queries in one Qwen batch, applies the same
category, vendor, and lifecycle filters to both PostgreSQL retrieval branches,
and reports Recall@5, MRR@5, nDCG@5, database latency, and adversarial challenge
slices. The checked-in baseline and its interpretation are in
[`artifacts/evaluation/retrieval_baseline.md`](artifacts/evaluation/retrieval_baseline.md).
The lexical branch uses PostgreSQL `tsvector`/`ts_rank_cd`; it is not BM25.

Run either confirmed reranker through the identical evaluation path:

```bash
docker compose --profile tools run --rm evaluate-retrieval --with-reranker

docker compose --profile tools run --rm evaluate-retrieval \
  --reranker-model-id Qwen/Qwen3-Reranker-0.6B
```

`--with-reranker` uses the configured MiniLM default; an explicit model ID
supports controlled alternatives such as the Qwen comparison.

The measured comparison is in
[`artifacts/evaluation/reranker_comparison.md`](artifacts/evaluation/reranker_comparison.md).
MiniLM is the preferred local CPU experiment: it improves hybrid RRF MRR@5
from `0.967` to `0.980` at roughly 64 ms reranking latency. Qwen reranking was
both slower and less accurate on this corpus. Vector-only remains strongest
overall at `0.990`, so no reranked mode is silently enabled by default.

The database layer uses synchronous Psycopg 3 connections with a small
connection pool. Alembic is used only for schema versioning; migrations contain
explicit PostgreSQL SQL, and retrieval queries will also remain explicit rather
than being hidden behind an ORM.

The single-query CLI and development utilities can run on the host. The
Dockerfile's `runtime` target remains a reusable base for the local LangGraph
application; its final workflow command will be added with the agent.

## Safety boundary

Model output is advisory. Every payment recommendation requires review by an
authorized human, and no application component may approve, schedule, or
transmit a payment.
