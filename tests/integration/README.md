# PostgreSQL integration tests

These tests verify the actual PostgreSQL 17 schema, pgvector codec, and search
columns. They are skipped during the default host-side unit test run.

Use Compose to migrate the database and run the complete suite:

```bash
docker compose --profile test run --rm test
```

Compose sets `INVOICE_TRIAGE_RUN_INTEGRATION=1` only inside the test container,
which prevents an ordinary `python -m pytest` from unexpectedly connecting to a
developer database.
