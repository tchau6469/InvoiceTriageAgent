# AP Invoice Triage Agent

A portfolio implementation of a human-reviewed accounts-payable triage agent
with custom hybrid retrieval. The agent extracts invoice data, checks vendors
and budgets, detects anomalies, retrieves contractual context, and drafts a
recommendation. It never approves or issues payment.

The locked project scope is documented in
`ai_solutions_engineer_project_spec.md`. Synthetic development data and retrieval
evaluation labels live under `fixtures/`.

## Current milestone

Step 1 establishes the Python package, strict Pydantic domain contracts, and
unit tests. PostgreSQL, document parsing, embeddings, retrieval, MCP tools,
LangGraph orchestration, AWS deployment, and the review dashboard are later
milestones.

## Local validation

The repository currently requires Python 3.12 or 3.13.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
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

The local image pins PostgreSQL 17 and pgvector 0.8.2 to align with the planned
Amazon RDS deployment. The `vector` extension is enabled when a new database
volume is initialized. Stop the service without deleting its data with:

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

The database layer uses synchronous Psycopg 3 connections with a small
connection pool. Alembic is used only for schema versioning; migrations contain
explicit PostgreSQL SQL, and retrieval queries will also remain explicit rather
than being hidden behind an ORM.

The Python application normally runs directly on the host during early RAG
development. The Dockerfile's `runtime` target is a reusable base for the later
AgentCore container; its final runtime command will be added with the agent.

## Safety boundary

Model output is advisory. Every payment recommendation requires review by an
authorized human, and no application component may approve, schedule, or
transmit a payment.
