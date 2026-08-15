# Invoice Triage Agent — Codex Project State

Last updated: 2026-08-15
Repository: `/home/tchau/InvoiceTriageAgent`

This file is a durable handoff for continuing the project after conversation
context is lost. It intentionally contains no passwords, credentials, tokens,
or other secret values.

## User collaboration preference

Confirm major architectural decisions with the user before implementing them.
Routine changes within an already confirmed design can proceed without another
confirmation. Explain RAG and infrastructure decisions in a teaching-oriented
way so the user can learn the workflow rather than only receive code.

## Project objective

Build a portfolio-quality AP Invoice Triage Agent aimed at AI Solutions
Engineer roles. The agent:

- Ingests fictional vendor invoices.
- Extracts normalized invoice data.
- Looks up vendors and checks operational status.
- Checks budgets and cost-center compatibility.
- Detects possible duplicate invoices and shipments.
- Retrieves applicable contracts and category policies through a custom RAG
  pipeline.
- Drafts a payment recommendation and supporting trace.
- Never approves, schedules, transmits, or executes payment.
- Always leaves the final payment decision to an authorized human reviewer.

The locked project requirements are in
`ai_solutions_engineer_project_spec.md`.

## Confirmed high-level architecture

The planned retrieval path is:

```text
Document sources
  -> parse
  -> heading-aware chunking
  -> embeddings
  -> PostgreSQL storage

Question
  -> pgvector semantic retrieval
  -> PostgreSQL native full-text retrieval
  -> Reciprocal Rank Fusion
  -> cross-encoder reranking
  -> top grounding chunks
  -> model reasoning/generation
```

The wider application architecture remains:

```text
Custom RAG pipeline
  -> MCP tools
  -> LangGraph orchestration
  -> Gemini 3.5 Flash structured reasoning
  -> human review dashboard
```

The user explicitly dropped AWS hosting, RDS, Bedrock, AgentCore, and IaC from
the active scope. Local Docker/Compose is the delivery environment. This keeps
the portfolio centered on custom RAG, MCP, LangGraph, prompting, evaluation,
and human review without introducing infrastructure the user does not want to
optimize for or pay to keep running.

## Important settled decisions

### Retrieval and BM25 terminology

`pgvector` does not implement BM25. Native PostgreSQL `tsvector` with
`ts_rank_cd` is ranked lexical/full-text retrieval, not true BM25.

The user confirmed the RDS-compatible design:

```text
pgvector vector search
  + PostgreSQL tsvector/ts_rank_cd lexical search
  -> Reciprocal Rank Fusion
  -> cross-encoder reranking
```

Do not call the lexical branch BM25 in project documentation or interviews.
Call it PostgreSQL native full-text ranking. Hybrid retrieval does not require
BM25; it requires complementary semantic and lexical signals.

True BM25 extensions such as `pg_textsearch` or ParadeDB `pg_search` were not
selected because they are not on the standard Amazon RDS PostgreSQL extension
allow-list. Adding OpenSearch or self-managed PostgreSQL would unnecessarily
change the current architecture.

### Python and packaging

- Package name: `invoice_triage`
- Project distribution name: `invoice-triage-agent`
- Supported Python: `>=3.12,<3.14`
- Current local/container Python: 3.13.12
- Packaging: `pyproject.toml` with setuptools and pip
- No Poetry or uv
- Pydantic 2 provides strict domain-boundary validation
- Monetary values use `Decimal`
- Dates use `date`
- Unknown model fields are rejected

### Grounding-document parsing and embeddings

The user selected and confirmed `Qwen/Qwen3-Embedding-0.6B` for local document
and query embeddings.

- Output dimension: 1024, matching the existing `vector(1024)` schema
- Local adapter: Sentence Transformers
- Document chunks: embedded without an instruction
- Queries: use a tailored accounts-payable retrieval instruction
- Vectors: L2-normalized for cosine retrieval
- Front matter: PyYAML `safe_load` with a strict allowed-field set
- CPU is the default device
- The optional `embeddings` dependency group keeps PyTorch out of ordinary
  migrations, structured loading, and tests
- The ingestion Docker target explicitly installs PyTorch from the official
  CPU wheel index so the image does not pull CUDA libraries

The deterministic SHA-256 embedder is test-only and must not be used for the
runtime corpus.

### PostgreSQL driver

The user confirmed Psycopg 3:

- Synchronous access initially
- `psycopg_pool.ConnectionPool`
- Native pgvector codecs registered on every pooled connection through
  `pgvector.psycopg.register_vector`
- Explicit parameterized SQL for repositories and retrieval
- No SQLAlchemy ORM in the application retrieval path
- Async may be introduced later if local MCP/agent concurrency demonstrates a
  need; it is not justified yet

### Database migrations

The user confirmed Alembic with explicit PostgreSQL SQL:

- Alembic manages revision order and installed schema state.
- SQLAlchemy Core is present only because Alembic uses it for connectivity and
  migration infrastructure.
- Do not adopt SQLAlchemy ORM without a new explicit decision.
- Do not depend on Alembic autogeneration for vector columns, generated
  `tsvector` expressions, GIN indexes, HNSW indexes, or vector operator classes.
- Migration URLs come from `INVOICE_TRIAGE_DATABASE_URL`; credentials are not
  stored in `alembic.ini`.

### Docker workflow

Current recommended local development:

```text
Host machine: Python source editing and fast unit tests
Docker:       PostgreSQL 17 + pgvector
```

The Python `Dockerfile` exists for:

- Reproducible containerized tests now.
- A reusable runtime image foundation for the local LangGraph application.

The normal PostgreSQL service uses a maintained prebuilt image, so it does not
need a custom database Dockerfile. Compose currently pins:

```text
pgvector/pgvector:0.8.2-pg17-bookworm
```

This preserves a modern, reproducible PostgreSQL/pgvector baseline locally.

## Synthetic corpus completed

The corpus contains 49 files under `fixtures/`:

```text
fixtures/
├── README.md
├── vendors/vendors.csv                 18 vendors
├── budgets/monthly_budgets.csv         13 budget records
├── contracts/                          18 vendor contracts
├── policies/                            6 category policies
├── invoices/                           20 invoice inputs
└── evaluation/
    ├── expected_findings.csv           20 ground-truth outcomes
    └── retrieval_queries.jsonl         50 labeled retrieval queries
```

The six categories are:

- `cloud_software`
- `office_supplies`
- `facilities_maintenance`
- `professional_services`
- `logistics_freight`
- `marketing_events`

Each policy contains exactly 12 heading-delimited clauses, producing 72 policy
chunks before any further chunk splitting. Contracts contain vendor-specific
rates, payment terms, PO rules, billing requirements, and security controls.

The 20 invoices contain the intended evaluation mix:

- 12 clear baseline invoices
- 3 deliberate duplicates
- 1 inactive-vendor/expired-contract/post-termination case
- 1 missing required PO
- 1 cost-center mismatch
- 1 budget-exceeded case
- 1 contract-rate overage

Important examples:

- `INV-2026-0013` duplicates `INV-2026-0001` by vendor invoice number,
  service period, and amount.
- `INV-2026-0014` duplicates `INV-2026-0005`.
- `INV-2026-0015` duplicates shipment `INV-2026-0009` through its bill of
  lading despite having a different invoice number.
- `INV-2026-0018` uses `MARKETING` instead of Prism Analytics' approved
  `DATA-PLATFORM` cost center.
- `INV-2026-0019` raises July facilities spending to `$12,850` against a
  `$12,500` budget.
- `INV-2026-0020` bills the Chicago-to-Detroit freight lane at `$1,650`
  instead of the contracted `$1,450`.

Runtime ingestion boundaries:

- Contracts and policies are RAG sources and will be embedded.
- Vendor and budget CSVs belong in structured relational tables.
- Invoices are transaction inputs, not grounding documents.
- `fixtures/evaluation/` is test-only ground truth and must never be exposed to
  the running agent or indexed into the retrieval corpus.

## Step 1 completed: project scaffold and domain contracts

Key files:

```text
pyproject.toml
.env.example
.gitignore
README.md
src/invoice_triage/config.py
src/invoice_triage/domain/models.py
```

Implemented domain models and enums include:

- `SourceDocument`
- `DocumentChunk`
- `Vendor`
- `VendorContact`
- `Invoice`
- `InvoiceLine`
- `RetrievalQuery`
- `SearchResult`
- `BudgetCheck`
- `MonthlyBudget`
- `DocumentType`
- `DocumentStatus`
- `VendorStatus`
- `VendorCategory`
- `PaymentTerms`
- `BudgetStatus`

Important model behavior:

- Strict unknown-field rejection
- Whitespace trimming and non-empty string validation
- Three-letter uppercase currency codes
- Exact `Decimal` money handling
- Contract/invoice vendor requirements
- Contract/policy category requirements
- Lifecycle and service-period date validation
- Retrieval provenance retained on every chunk
- Reranker score becomes `SearchResult.final_score` when present
- Budget status is derived deterministically, prioritizing cost-center mismatch
  over available amount

`AppSettings` reads namespaced `INVOICE_TRIAGE_*` variables plus the provider
standard `GEMINI_API_KEY`/`GOOGLE_API_KEY` secret. It does not implicitly load
`.env`; Compose loads `.env`, and a host shell/runner must export variables when
running directly on the host.

The retrieval and evaluation packages are implemented along with ingestion,
embeddings, and structured/RAG repositories:

```text
src/invoice_triage/retrieval/
src/invoice_triage/evaluation/
src/invoice_triage/reranking/
src/invoice_triage/cli/
src/invoice_triage/mcp_server/
```

They support vector-only, lexical-only, RRF hybrid, and optional cross-encoder
reranked modes.

## Docker and Compose completed

Key files:

```text
Dockerfile
.dockerignore
compose.yaml
docker/postgres/init/001-enable-vector.sql
```

`Dockerfile` targets:

- `runtime`: installs the application and copies runtime fixtures, migrations,
  and scripts. It intentionally has no final command until the local LangGraph
  entrypoint is implemented.
- `ingestion`: installs CPU-only PyTorch and the optional Sentence Transformers
  dependency group, then copies the corpus, migrations, and scripts.
- `mcp`: installs the local embedding runtime plus FastMCP and starts the
  `invoice-triage-mcp` stdio entry point.
- `test`: installs development and MCP dependencies, migrations, fixtures, and
  tests; its default command is pytest.

Compose services:

- `postgres`: default local database service with persistent named volume and
  health check.
- `migrate`: optional `tools` profile; applies Alembic through `head`.
- `load-fixtures`: optional `tools` profile; applies migrations and then loads
  structured vendor and budget fixtures transactionally.
- `load-invoices`: optional `tools` profile; applies migrations, loads vendor
  and budget prerequisites, then loads normalized invoices and identifiers.
- `model-cache-init`: optional `tools` and `mcp` profiles; makes the named
  Hugging Face cache volume writable by the fixed non-root application UID.
- `ingest-documents`: optional `tools` profile; installs the CPU-only local
  embedding runtime, applies migrations, and ingests Qwen vectors.
- `evaluate-retrieval`: optional `tools` profile; embeds the 50 labeled queries
  and benchmarks vector, lexical, RRF, and an optional cross-encoder mode
  against the live corpus.
- `search`: optional `tools` profile; runs one user-supplied query with vector
  retrieval by default or an explicitly selected lexical, hybrid, or reranked
  mode.
- `mcp-server`: optional `mcp` profile; exposes read-only `lookup_vendor`,
  `check_budget`, `flag_duplicate`, `retrieve_context`, and
  `extract_invoice_data` tools over stdio with PostgreSQL, Gemini, and the
  local model cache.
- `test`: optional `test` profile; applies migrations and then runs unit and
  live PostgreSQL integration tests.

The `huggingface-cache` named volume stores public model weights across
one-shot ingestion containers. The application UID/GID is fixed at 10001.

The local user created `.env`, supplied a PostgreSQL password, started the
database with `docker compose up -d postgres`, and verified it was running.
Never read, print, commit, or reproduce the user's secret value. `.env` is
ignored by Git.

Relevant `.env` fields are:

```dotenv
POSTGRES_DB=invoice_triage
POSTGRES_USER=invoice_triage
POSTGRES_PASSWORD=<secret local password>
POSTGRES_PORT=5432
INVOICE_TRIAGE_DATABASE_URL=postgresql://invoice_triage:<same URL-encoded password>@localhost:5432/invoice_triage
INVOICE_TRIAGE_EMBEDDING_MODEL_ID=Qwen/Qwen3-Embedding-0.6B
INVOICE_TRIAGE_EMBEDDING_DIMENSIONS=1024
INVOICE_TRIAGE_EMBEDDING_DEVICE=cpu
INVOICE_TRIAGE_EMBEDDING_BATCH_SIZE=8
INVOICE_TRIAGE_RRF_K=60
INVOICE_TRIAGE_RERANK_CANDIDATES=10
INVOICE_TRIAGE_RERANKER_MODEL_ID=cross-encoder/ms-marco-MiniLM-L6-v2
INVOICE_TRIAGE_RERANKER_DEVICE=cpu
INVOICE_TRIAGE_RERANKER_BATCH_SIZE=4
INVOICE_TRIAGE_RERANKER_MAX_LENGTH=512
INVOICE_TRIAGE_REASONING_PROVIDER=gemini
INVOICE_TRIAGE_REASONING_MODEL_ID=gemini-3.5-flash
INVOICE_TRIAGE_INVOICE_SOURCE_ROOT=fixtures/invoices
GEMINI_API_KEY=<secret Google AI Studio API key>
```

No external PostgreSQL account is required for local development. The Compose
image creates the database and role from these values. No AWS/RDS credentials
belong in local Compose files.

## Database foundation completed

Dependencies added in `pyproject.toml`:

```text
alembic>=1.18,<1.19
pgvector>=0.4,<0.5
pydantic>=2.12,<3
psycopg[binary,pool]>=3.3,<3.4
SQLAlchemy>=2.0,<2.1
fastmcp==3.4.4 (MCP extra; exact tested pin)
google-genai>=2,<3 (reasoning extra)
pytest>=9,<10 (development extra)
```

### Connection management

`src/invoice_triage/storage/postgres.py` implements `Database`:

- Lazy construction with no network I/O
- `Database.from_settings()` without logging the secret URL
- Explicit `open()` and `close()` lifecycle
- Context-managed transactional connections
- Dictionary rows
- Pool connection checks
- pgvector codec registration for each new connection
- Simple `check_health()` query
- Configurable minimum and maximum pool sizes

### Migration chain

Alembic is configured through:

```text
alembic.ini
migrations/env.py
migrations/script.py.mako
```

Current revisions:

```text
0001_enable_extensions
  -> 0002_structured_tables
  -> 0003_rag_tables
  -> 0004_search_indexes
  -> 0005_title_search
  -> 0006_invoice_records
```

Revision responsibilities:

1. `0001_enable_extensions.py`
   - `CREATE EXTENSION IF NOT EXISTS vector`

2. `0002_create_structured_tables.py`
   - `vendors`
   - `monthly_budgets`
   - domain checks for status, category, currency, payment terms, and amounts

3. `0003_create_rag_tables.py`
   - `source_documents`
   - `document_chunks`
   - `JSONB` metadata
   - SHA-256 content hashes
   - `vector(1024)` embedding column
   - stored generated `search_vector`
   - heading text assigned weight A
   - body content assigned weight B
   - English PostgreSQL text-search configuration

4. `0004_create_search_indexes.py`
   - relational lookup indexes
   - GIN aliases index
   - JSONB metadata indexes
   - GIN `search_vector` index
   - HNSW cosine-distance vector index using `vector_cosine_ops`

5. `0005_add_titles_to_search_vector.py`
   - rebuilds the generated full-text vector and its GIN index
   - adds the document title at weight A alongside section headings at weight A
     and body content at weight B

6. `0006_create_invoice_records.py`
   - `invoice_records` with exact money, lifecycle state, service period,
     receipt ordering, source provenance, and vendor foreign key
   - `invoice_identifiers` for typed shipment and purchase-order references
   - partial indexes for active duplicate checks and committed budget sums

The local database was successfully migrated to:

```text
Alembic head:     0006_invoice_records
pgvector version: 0.8.2
```

The Compose PostgreSQL service was last verified healthy with port 5432
published to localhost. The persistent volume must not be deleted casually.

## Tests and validation completed

Test locations:

```text
tests/unit/test_config.py
tests/unit/test_fixture_schema_alignment.py
tests/unit/test_models.py
tests/unit/test_postgres.py
tests/unit/test_document_parser.py
tests/unit/test_document_chunker.py
tests/unit/test_document_pipeline.py
tests/unit/test_embeddings.py
tests/unit/test_hybrid_search.py
tests/unit/test_invoice_records.py
tests/unit/test_mcp_retrieval.py
tests/unit/test_mcp_server.py
tests/unit/test_mcp_structured_tools.py
tests/unit/test_reranking.py
tests/unit/test_retrieval_evaluation.py
tests/unit/test_retrieval_metrics.py
tests/unit/test_search_cli.py
tests/unit/test_structured_ingestion.py
tests/integration/test_postgres.py
tests/integration/test_document_repository.py
tests/integration/test_invoice_repository.py
tests/integration/test_mcp_structured_tools.py
tests/integration/test_retrieval.py
tests/integration/test_structured_fixtures.py
```

The integration suite is skipped by ordinary host-side pytest unless
`INVOICE_TRIAGE_RUN_INTEGRATION=1`. Compose sets it inside the test container.

The last complete rebuilt containerized test run passed:

```text
111 passed
```

The live integration checks verified:

- Database health
- pgvector extension version 0.8.2
- Alembic head `0006_invoice_records`
- Expected relational/RAG tables
- Vector, lexical, RRF, and cross-encoder reranking behavior
- Single-query CLI parsing, mode selection, filtering, and JSON output
- GIN full-text index
- HNSW vector index
- Native vector decoding through pgvector-python
- PostgreSQL English full-text matching
- Structured fixture parsing and validation
- Transactional vendor and budget upserts
- Idempotent repeated loads
- Vendor ID and case-insensitive alias lookup
- Inactive-vendor preservation
- Monthly budget lookup
- Validation-before-write behavior for malformed fixture input
- Strict Markdown/YAML parsing and corpus isolation
- Stable heading-aware chunk IDs and intact Markdown tables
- Qwen query/document prompt asymmetry
- cosine retrieval through pgvector with a native `Vector` query parameter
- lexical retrieval through the generated `tsvector`
- independently selectable vector, lexical, and RRF service modes
- RRF rank arithmetic without mixing raw branch scores
- Recall@k, MRR@k, and binary nDCG@k metric behavior
- strict evaluation-label validation, including optional historical
  `as_of_date` values
- date-aware lifecycle filtering for terms applicable on an `as_of_date`
- Live document/chunk upserts with 1024-dimensional vectors
- Generated `tsvector` matches
- Stale chunk deletion and safe heading reordering
- FastMCP tool discovery, typed schema validation, structured output, and
  read-only annotations
- Live MCP vendor alias/inactive-status resolution and deterministic monthly
  budget outcomes using exact decimal arithmetic
- Strict normalization of all 20 Markdown invoice inputs
- Idempotent invoice and typed-identifier persistence
- Exact vendor-number, service-period/amount, and shipment-identifier duplicate
  detection against earlier active records
- Budget aggregation that adds only persisted `committed` invoices to the base
  monthly snapshot

The first containerized run exposed two test-packaging issues that were fixed:

- Identically named unit/integration test modules conflicted, so `__init__.py`
  files were added to make the directories distinct packages.
- The non-root test container could not create `.pytest_cache`, so its test
  target sets `PYTEST_ADDOPTS="-p no:cacheprovider"`.

## Common commands

Start only the database:

```bash
docker compose up -d postgres
docker compose ps
```

Apply outstanding migrations:

```bash
docker compose --profile tools run --rm migrate
```

Load or refresh structured vendor and budget fixtures:

```bash
docker compose --profile tools run --rm load-fixtures
```

Build the CPU embedding runtime and ingest contracts/policies:

```bash
docker compose --profile tools run --build --rm ingest-documents
```

Benchmark vector, lexical, hybrid, and optional reranked retrieval:

```bash
docker compose --profile tools run --build --rm evaluate-retrieval
```

Run one query with the measured vector default or an explicit alternative:

```bash
docker compose --profile tools run --build --rm search "query text"
docker compose --profile tools run --rm search "CSP-05" --mode lexical
docker compose --profile tools run --rm search "query text" --mode hybrid
docker compose --profile tools run --rm search "query text" --mode hybrid_reranked
docker compose --profile tools run --rm search "historical terms" --mode lexical --as-of-date 2025-09-30
```

Build and launch the MCP server as a client-managed stdio subprocess:

```bash
docker compose --profile mcp build mcp-server
docker compose --profile mcp run --rm -T mcp-server
```

Apply migrations and run all tests, including integration tests:

```bash
docker compose --profile test run --rm test
```

Stop containers without deleting database data:

```bash
docker compose down
```

Do not add `--volumes` unless deleting the local database is explicitly
intended and approved.

For a host Python environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

Install `.[embeddings]` as well only when running Qwen directly on the host.

If running Alembic directly on the host, ensure
`INVOICE_TRIAGE_DATABASE_URL` is exported because application settings do not
parse `.env` automatically.

Inspect database versions safely through the container's own environment:

```bash
docker compose exec -T postgres sh -c \
  'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --command "SELECT version_num FROM alembic_version;"'
```

## Current repository status warning

The earlier application scaffold and database foundation are tracked. The
structured-loading, RAG-ingestion/retrieval, CLI, and MCP milestones have
working-tree changes and new files that have not been committed during this
interaction. Review `git status` and create a normal checkpoint commit when
desired. Do not discard the new loaders, ingestion/retrieval pipeline, MCP
server, or tests.

## Work not yet implemented

The following are still pending:

- The final planned MCP tool: `draft_recommendation`
- LangGraph workflow
- CI/CD workflow
- Audit logging
- Human review dashboard
- End-to-end agent evaluation, traces, latency, and aggregate token measurement
- AI usage guardrails document

## Structured fixture loading completed

The structured data milestone is implemented in:

```text
src/invoice_triage/domain/models.py           MonthlyBudget model
src/invoice_triage/storage/repositories.py    VendorRepository, BudgetRepository
src/invoice_triage/ingestion/structured.py    CSV validation and atomic loader
scripts/load_structured_fixtures.py            argparse CLI
```

Behavior:

- Exact CSV header validation
- All rows validated before database access
- Duplicate fixture business keys rejected
- `YYYY-MM` budget periods converted to first-of-month dates
- Parameterized Psycopg SQL
- Vendor upsert by `vendor_id`
- Budget upsert by period/category/cost center
- Both datasets written in one transaction
- Case-insensitive legal name, display name, and alias lookup
- Idempotent repeated execution

The actual CLI was run twice against the persistent local database. Final
verified state:

```text
vendors: 18
budgets: 13
VND-1010 status: inactive
VND-1010 cost center: TECH-PROJECTS
Facilities July budget: 12500.00
Facilities base committed amount: 5000.00
```

## Vector, lexical, and RRF retrieval completed

Implemented files:

```text
src/invoice_triage/retrieval/vector_search.py
src/invoice_triage/retrieval/keyword_search.py
src/invoice_triage/retrieval/hybrid_search.py
src/invoice_triage/retrieval/service.py
src/invoice_triage/evaluation/metrics.py
src/invoice_triage/evaluation/retrieval_eval.py
scripts/evaluate_retrieval.py
artifacts/evaluation/retrieval_baseline.md
```

Settled retrieval baseline:

- vector and lexical branches each retrieve 20 candidates
- vector search uses pgvector cosine distance and filtered HNSW iterative scans
- lexical search uses PostgreSQL English `tsvector`, safely quoted
  OR-normalized query lexemes, and `ts_rank_cd(..., 32)`; it is not BM25
- both branches apply the same category, vendor, metadata, and lifecycle filters
- without `as_of_date`, only active documents are eligible
- with `as_of_date`, active or expired documents are eligible only when their
  effective/expiration range contains that date; this replaces the unsafe broad
  `include_expired` switch
- unweighted Reciprocal Rank Fusion uses `k = 60`
- RRF combines ranks rather than incomparable raw vector and lexical scores
- callers must select vector, lexical, or hybrid mode explicitly; the service
  does not silently default to hybrid before evaluation justifies that choice
- the evaluation runner embeds all 50 queries once as a Qwen batch and reuses
  those vectors across modes
- `hybrid_reranked` fuses the top 10 candidates, releases the database
  connection, scores enriched title/section/content passages, and returns five
  while preserving vector, lexical, RRF, and reranker scores

The evaluation set now contains 30 natural-language baseline queries and 20
adversarial exact-match queries: four each for invoice numbers, clause IDs,
acronyms, vendor aliases, and dollar amounts. Invoice-number cases preserve the
runtime boundary: invoices are not indexed, and structured resolution supplies
the vendor/category filter before grounding retrieval.

Measured local baseline on the expanded 50-query set:

| Mode | Recall@5 | MRR@5 | nDCG@5 | Mean DB ms |
|---|---:|---:|---:|---:|
| vector | 1.000 | 0.990 | 0.993 | 2.16 |
| lexical | 1.000 | 0.964 | 0.973 | 1.91 |
| hybrid RRF | 1.000 | 0.967 | 0.975 | 3.21 |

The latest rebuilt image embedded the 50-query Qwen batch on CPU in about 31.76
seconds, approximately 635 ms per query amortized. On the clause-ID slice,
vector MRR@5 is `0.875`
while lexical and RRF both reach `1.000`, demonstrating a real lexical benefit.
Vector-only retrieval remains strongest overall. Do not tune RRF merely to
force an aggregate win on this same evaluation set.

The first adversarial run exposed and fixed a lexical parser issue. PostgreSQL
normalizes `CSP-05` into `csp` and `-05`; `websearch_to_tsquery` interpreted the
leading hyphen as NOT. The query builder now safely quotes PostgreSQL-normalized
lexemes before constructing an OR `tsquery`, preserving exact clause IDs. A
live integration test covers the behavior.

## Cross-encoder reranking completed and evaluated

Implemented files:

```text
src/invoice_triage/reranking/client.py
src/invoice_triage/reranking/service.py
src/invoice_triage/reranking/__init__.py
tests/unit/test_reranking.py
artifacts/evaluation/reranker_comparison.md
```

The user confirmed a model-independent Sentence Transformers `CrossEncoder`
adapter and a controlled comparison of:

- `Qwen/Qwen3-Reranker-0.6B` with a tailored AP relevance instruction
- `cross-encoder/ms-marco-MiniLM-L6-v2` as the CPU latency control

Both models reranked the same RRF top 10 to a final top 5 over all 50 labels.
The evaluation separates model initialization/warm-up, steady-state reranker
latency, database latency, total retrieval latency, and process peak RSS.

Measured local CPU results:

| Mode/model | Recall@5 | MRR@5 | nDCG@5 | Mean rerank ms | p95 total ms |
|---|---:|---:|---:|---:|---:|
| vector only | 1.000 | 0.990 | 0.993 | — | ~3.5 |
| hybrid RRF | 1.000 | 0.967 | 0.975 | — | ~4.1 |
| RRF + Qwen3 reranker | 1.000 | 0.940 | 0.956 | 10057.06 | 12673.85 |
| RRF + MiniLM reranker | 1.000 | 0.980 | 0.985 | 63.97 | 96.06 |

Process peak RSS with both embedding and reranking models resident was about
3388 MiB for Qwen and 1621 MiB for MiniLM. MiniLM achieved perfect MRR@5 on all
five adversarial slices and is the preferred experimental local CPU reranker.
Qwen is rejected as the CPU default for this corpus because it was both slower
and less accurate. Vector-only remains strongest overall, so retrieval modes
remain explicit and no reranker is silently enabled by default.

## Single-query CLI completed

Implemented files and entry points:

```text
src/invoice_triage/cli/search.py
src/invoice_triage/cli/__init__.py
scripts/search.py
tests/unit/test_search_cli.py
pyproject.toml: invoice-triage-search
compose.yaml: search service in the tools profile
```

The CLI accepts one query and uses `vector` by default because it remains the
strongest aggregate retrieval mode on the labeled corpus. Alternative modes
are explicit through `--mode lexical`, `--mode hybrid`, and
`--mode hybrid_reranked`. The reranker is initialized only for the reranked
mode. Other supported options are `--top-k`, `--category`, `--vendor-id`,
`--as-of-date`, `--metadata-filter`, `--reranker-model-id`, and `--json`.
An override supplied through `--reranker-model-id` is rejected unless the
reranked mode is selected.

Live Compose validation succeeded for all four modes. The default vector query
returned policy clause `CSP-02` for a cloud-software approval question, lexical
retrieval resolved exact clause ID `CSP-05`, hybrid returned stage-specific
vector/lexical/RRF scores, and MiniLM reranking restored `CSP-02` to rank one.
The JSON response retains the validated query, explicit mode, result count,
complete chunk provenance, and all available stage scores.

## MCP vendor, budget, and retrieval tools completed

The first MCP milestone established two related decisions:

1. Expose a typed, read-only FastMCP `retrieve_context` tool over local stdio.
2. Replace the broad `include_expired` switch with exact `as_of_date` lifecycle
   filtering in the domain, CLI, evaluation labels, SQL branches, and MCP tool.

Implemented files and entry points:

```text
src/invoice_triage/mcp_server/models.py
src/invoice_triage/mcp_server/retrieval_tool.py
src/invoice_triage/mcp_server/structured_tools.py
src/invoice_triage/mcp_server/server.py
tests/unit/test_mcp_retrieval.py
tests/unit/test_mcp_server.py
tests/unit/test_mcp_structured_tools.py
tests/integration/test_mcp_structured_tools.py
pyproject.toml: invoice-triage-mcp
compose.yaml: mcp-server service in the mcp profile
```

The public tool accepts:

- required `query` (1–2000 characters)
- `mode`, defaulting to the evaluated `vector` baseline
- `top_k`, default 5 and hard-limited to 10
- optional `category`, `vendor_id`, and `as_of_date`

The allowlisted structured response includes applied filters, `found` or
`not_found`, stable chunk citation IDs, passage content, contract/policy
provenance, lifecycle dates, and stage-specific diagnostic scores. It does not
expose arbitrary chunk metadata, invoices as grounding documents, or any
payment mutation. Empty retrieval is a normal `not_found`; database/model
failures remain errors so an agent cannot mistake an outage for missing policy.

FastMCP is pinned to the exact locally tested version `3.4.4`. Tool annotations
mark retrieval read-only, non-destructive, idempotent, and closed-world. The
server uses one process-lifetime database pool and lazy local embedding/reranker
clients. Version 1 intentionally retains the synchronous retrieval service
inside an async FastMCP handler for the single-client stdio workflow. Revisit
the database/runtime concurrency model before introducing multi-client HTTP.

Live MCP protocol validation launched the real Compose stdio server, discovered
`retrieve_context`, and queried PostgreSQL with Qwen embeddings. The no-mode
call used `vector` and returned `POL-CLOUD-2026:csp-02-new-subscription-threshold`.
A historical lexical call with `as_of_date=2025-09-30` returned the expired but
then-applicable clause `CTR-VND-1010-2025:expiration`.

The next confirmed implementation added the structured vendor and budget
tools, followed by invoice persistence and duplicate detection:

- `lookup_vendor(identifier)` tries an exact stable vendor ID first, then exact
  case-insensitive legal name, display name, and alias matching. It explicitly
  reports `found`, `not_found`, or `ambiguous` and excludes vendor contact and
  remittance fields from the public response.
- `check_budget(invoice_id)` loads the candidate from PostgreSQL, derives its
  vendor, month, cost center, amount, and currency, and reads the matching
  budget. Callers cannot override those facts. Prerequisite statuses include
  `invoice_not_found`, `vendor_not_found`, `budget_not_found`, and
  `currency_mismatch`; evaluated outcomes are `within_budget`,
  `budget_exceeded`, and `cost_center_mismatch`.
- `flag_duplicate(invoice_id)` compares the candidate only with earlier active
  records using exact vendor invoice number, same-vendor service period plus
  amount, and shared bill-of-lading, tracking, packing-slip, or
  proof-of-delivery identifiers. Purchase-order reuse is retained but is not a
  duplicate signal by itself. Results are review flags and never mutate status.

All public monetary values use exact decimal strings in MCP JSON while internal
calculations remain `Decimal`. The effective committed amount is the stored
`monthly_budgets.committed_amount` snapshot plus matching persisted invoices in
`committed` status. The current candidate is excluded from that sum and then
projected once; `pending_review` candidates do not consume budget prematurely.

The fixture loader assigned invoices 0001–0012 to `committed` and 0013–0020 to
`pending_review`, all with deterministic aware receipt timestamps. The live
database contains 20 invoices and 17 typed identifiers. It reproduces the
intended duplicate pairs 0013→0001, 0014→0005, and 0015→0009. July facilities
budget checking adds `$6,400.00` of committed persisted invoices to the
`$5,000.00` base snapshot, so candidate 0019 projects `$12,850.00` against
`$12,500.00` and reports an overage of `$350.00`.

The earlier live FastMCP stdio validation discovered the original four tools.
`flag_duplicate("INV-2026-0015")` returned the committed invoice
0009 with the shared BOL and proof-of-delivery identifiers, while
`check_budget("INV-2026-0019")` returned the exact budget figures above.

Invoice milestone implementation map:

```text
migrations/versions/0006_create_invoice_records.py
src/invoice_triage/domain/models.py
src/invoice_triage/ingestion/invoice_records.py
src/invoice_triage/storage/repositories.py          InvoiceRepository
src/invoice_triage/mcp_server/models.py
src/invoice_triage/mcp_server/structured_tools.py
src/invoice_triage/mcp_server/server.py              flag_duplicate tool
scripts/load_invoice_fixtures.py
compose.yaml                                         load-invoices service
tests/unit/test_invoice_records.py
tests/integration/test_invoice_repository.py
```

## Gemini extraction and graph-state milestone completed

The user selected Gemini 3.5 Flash on its free tier for local reasoning, with
synthetic data only. The implementation keeps that choice replaceable:

```text
src/invoice_triage/reasoning/base.py       provider-neutral async protocol
src/invoice_triage/reasoning/extraction.py strict model-facing schema
src/invoice_triage/reasoning/gemini.py     official google-genai adapter
src/invoice_triage/orchestration/state.py  validated LangGraph state contract
src/invoice_triage/mcp_server/extraction_tool.py
```

`extract_invoice_data(invoice_id)` is now the fifth MCP tool. It looks up the
persisted record in PostgreSQL, uses its `source_path`, and reads only relative
Markdown files contained by the configured `fixtures/invoices` root. The model
never receives a path argument. The reader blocks absolute paths, traversal,
non-Markdown files, sources larger than 256 KB, and unreadable sources.

Gemini receives an explicit instruction to treat the invoice as untrusted data,
ignore instructions inside it, extract only supported facts, avoid payment
recommendations, normalize dates/terms/decimals, and emit one object per line.
The provider response uses native JSON Schema, is validated as a narrow
`InvoiceExtractionPayload`, converted into the stricter domain `Invoice`, and
checked again for an exact requested invoice ID. Public MCP output excludes
operational status, receipt time, source path, hashes, and arbitrary metadata.

The official `google-genai>=2,<3` SDK is isolated in the `reasoning` optional
dependency group. `AppSettings` accepts the selected model through
`INVOICE_TRIAGE_REASONING_MODEL_ID` and the secret through `GEMINI_API_KEY`
(with `GOOGLE_API_KEY` as a fallback). Secrets remain `SecretStr` values and
are never written to this state file. Compose passes these variables only to
the MCP service. The application still does not parse `.env` itself; Compose
performs that injection.

The first live call surfaced that the SDK's OpenAPI-style `response_schema`
rejected Pydantic's strict `additionalProperties: false`. The adapter was
corrected to use `response_json_schema`, which supports native JSON Schema.
The live retry succeeded for synthetic `INV-2026-0019`, returning the exact
vendor invoice number, vendor ID, date, currency, `$1,450.00` total, one labor
line, Net 30 terms, facilities cost center, PO, and single-day service period.
Gemini reported 411 input tokens, 187 candidate-output tokens, and 1,630 total
tokens (including thinking tokens). The API key was not displayed.

Fast host tests passed `89 passed, 22 skipped`; the rebuilt Compose suite passed
all `111` unit and live PostgreSQL tests. New coverage includes strict settings,
provider adapter behavior, JSON Schema selection, source-path containment,
missing records, identity mismatch, MCP discovery/structured output, and the
initial human-reviewed graph-state invariant.

## Recommended immediate next step

Implement `draft_recommendation` as the final MCP tool using the same
provider-neutral structured-output boundary. Its input must be the already
validated extraction plus deterministic vendor, duplicate, budget, and RAG
evidence—not raw free-form claims from the model. After that, compile the first
LangGraph with deterministic nodes, explicit anomaly routes, and a mandatory
human-review interrupt.

## Decisions that still require user confirmation

Before their implementation, confirm these major choices:

- The exact structured recommendation schema and recommendation labels
- Whether the graph calls in-process adapters or an MCP client subprocess in
  the first local end-to-end version
- Any move from synchronous to asynchronous database access

Changing embedding dimensions requires a database migration and re-embedding
the corpus, so it must be decided before production ingestion.

## Guardrails for future implementation

- Never index files under `fixtures/evaluation/` into runtime retrieval.
- Never put passwords or complete secret-bearing URLs in tracked files or logs.
- Keep migrations explicit and reviewable.
- Keep application retrieval SQL visible; do not introduce an ORM implicitly.
- Preserve document ID, source path, heading, vendor/category scope, lifecycle
  status, dates, and content hash on chunks.
- Make ingestion idempotent.
- Benchmark vector-only, lexical-only, hybrid, and hybrid-plus-reranking modes
  independently.
- Report Recall@5, MRR, nDCG@5, and latency using the 50 labeled queries and
  preserve per-challenge slices.
- Maintain the invariant that the agent can recommend but never approve or pay.

## RAG document ingestion completed

Implemented files:

```text
src/invoice_triage/ingestion/parser.py
src/invoice_triage/ingestion/chunker.py
src/invoice_triage/ingestion/pipeline.py
src/invoice_triage/embeddings/client.py
src/invoice_triage/storage/repositories.py
scripts/ingest_grounding_documents.py
```

Behavior:

- Discovers exactly 18 contracts and 6 policies; invoices and evaluation files
  are excluded by construction.
- Requires YAML front matter and exactly one H1 title.
- Creates one chunk per H2 section and an overview chunk only when pre-section
  body text exists.
- Preserves each short clause and Markdown table intact.
- Produces stable `document_id:heading-slug` chunk IDs.
- Embeds `document title + section heading + section body`.
- Stores embedding model, dimension, and text-recipe version in chunk metadata.
- Computes SHA-256 hashes and retains source, scope, lifecycle, and ordinal
  provenance.
- Validates the complete corpus and generates all embeddings before opening the
  atomic database write transaction.
- Safely handles deleted, renamed, and reordered sections during re-ingestion.

The real ingestion command completed successfully against the persistent local
database. Verified state:

```text
source_documents:     24
document_chunks:     195
missing embeddings:    0
wrong dimensions:      0
Qwen-provenance rows: 195
full-text "payment terms" matches: 24
```

The public model weights are cached in the Docker `huggingface-cache` volume.
Do not use `docker compose down --volumes` unless both the PostgreSQL data and
downloaded model cache are intentionally being deleted.
