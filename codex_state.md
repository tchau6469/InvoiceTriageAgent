# Invoice Triage Agent — Codex Project State

Last updated: 2026-08-12  
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
  -> Bedrock inference and guardrails
  -> AgentCore deployment
  -> human review dashboard
```

AWS production deployment will eventually use Amazon RDS for PostgreSQL with
pgvector. Local development uses the same database family through Docker.

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

### PostgreSQL driver

The user confirmed Psycopg 3:

- Synchronous access initially
- `psycopg_pool.ConnectionPool`
- Native pgvector codecs registered on every pooled connection through
  `pgvector.psycopg.register_vector`
- Explicit parameterized SQL for repositories and retrieval
- No SQLAlchemy ORM in the application retrieval path
- Async may be introduced later if MCP/AgentCore concurrency demonstrates a
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
- A reusable runtime image foundation for AgentCore later.

The normal PostgreSQL service uses a maintained prebuilt image, so it does not
need a custom database Dockerfile. Compose currently pins:

```text
pgvector/pgvector:0.8.2-pg17-bookworm
```

This was chosen to align with the pgvector version available on the selected
Amazon RDS PostgreSQL 17 path at the time of implementation.

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
    └── retrieval_queries.jsonl         30 labeled retrieval queries
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

`AppSettings` reads only namespaced `INVOICE_TRIAGE_*` variables. It does not
implicitly load `.env`; Compose loads `.env`, and a host shell/runner must export
variables when running directly on the host.

The following future-stage packages exist but mostly remain scaffolds:

```text
src/invoice_triage/ingestion/
src/invoice_triage/embeddings/
src/invoice_triage/retrieval/
src/invoice_triage/evaluation/
src/invoice_triage/storage/repositories.py
```

Do not mistake their presence for completed implementations.

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
  and scripts. It intentionally has no final agent command yet because the
  AgentCore entrypoint has not been implemented.
- `test`: installs development dependencies, migrations, fixtures, and tests;
  its default command is pytest.

Compose services:

- `postgres`: default local database service with persistent named volume and
  health check.
- `migrate`: optional `tools` profile; applies Alembic through `head`.
- `test`: optional `test` profile; applies migrations and then runs unit and
  live PostgreSQL integration tests.

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

The local database was successfully migrated to:

```text
Alembic head:     0004_search_indexes
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
tests/integration/test_postgres.py
```

The integration suite is skipped by ordinary host-side pytest unless
`INVOICE_TRIAGE_RUN_INTEGRATION=1`. Compose sets it inside the test container.

The last complete containerized test run passed:

```text
25 passed
```

The live integration checks verified:

- Database health
- pgvector extension version 0.8.2
- Alembic head `0004_search_indexes`
- Expected relational/RAG tables
- GIN full-text index
- HNSW vector index
- Native vector decoding through pgvector-python
- PostgreSQL English full-text matching

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

If running Alembic directly on the host, ensure
`INVOICE_TRIAGE_DATABASE_URL` is exported because application settings do not
parse `.env` automatically.

Inspect database versions safely through the container's own environment:

```bash
docker compose exec -T postgres sh -c \
  'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --command "SELECT version_num FROM alembic_version;"'
```

## Current repository status warning

At the time of this snapshot, the application scaffold and database foundation
appear as untracked files in `git status`; they have not been committed during
this interaction. The synthetic corpus and original spec were already tracked.
Before major further work, review `git status` and create a normal checkpoint
commit if desired. Do not discard untracked files.

## Work not yet implemented

The following are still pending:

- Structured vendor CSV loader and repository
- Structured monthly-budget CSV loader and repository
- Markdown/YAML-front-matter parser
- Heading-aware chunker
- Embedding provider/client implementation
- Chunk/document upsert repository
- Vector-only retrieval
- PostgreSQL lexical retrieval
- Reciprocal Rank Fusion
- Cross-encoder reranking
- Retrieval benchmark metrics and runner
- MCP tool server and six tools
- LangGraph workflow
- Bedrock inference and guardrails
- AgentCore deployment
- Terraform/CDK infrastructure
- CI/CD workflow
- Audit logging
- Human review dashboard
- Token/cost measurement
- AI usage guardrails document

## Recommended immediate next step

Implement structured fixture loading before RAG document parsing:

1. Implement `VendorRepository` and `BudgetRepository` with explicit,
   parameterized Psycopg SQL.
2. Add CSV loaders for `fixtures/vendors/vendors.csv` and
   `fixtures/budgets/monthly_budgets.csv`.
3. Convert budget periods like `2026-07` to first-of-month PostgreSQL dates.
4. Upsert records idempotently in transactions.
5. Test that running the loader twice produces no duplicate records.
6. Verify exact counts: 18 vendors and 13 budget rows.
7. Add lookup tests for aliases, inactive status, cost center, payment terms,
   and the facilities budget anomaly.

After structured loading is reliable, implement the ingestion vertical slice:

```text
one policy Markdown file
  -> parse YAML front matter and body
  -> split into heading sections
  -> retain tables and metadata
  -> generate stable document/chunk IDs and SHA-256 hashes
  -> temporarily use a deterministic test embedding
  -> upsert source document and chunks
  -> verify generated tsvector content
```

Then extend to all 24 RAG source documents (18 contracts + 6 policies) before
introducing a real embedding provider.

## Decisions that still require user confirmation

Before their implementation, confirm these major choices:

- Exact embedding model/provider for local development and Bedrock deployment
- Embedding dimension if different from the current schema's `vector(1024)`
- Cross-encoder reranker model and hosting method
- Exact RRF constant and candidate counts after initial evaluation
- Whether source YAML parsing uses PyYAML or a narrower custom parser
- Repository/loader command interface and whether a CLI framework is warranted
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
- Report Recall@5, MRR, nDCG@5, and latency using the 30 labeled queries.
- Maintain the invariant that the agent can recommend but never approve or pay.
