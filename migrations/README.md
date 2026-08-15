# PostgreSQL migrations

Alembic records and applies the schema history in `versions/`. Migrations use
explicit PostgreSQL SQL so vector types, generated full-text data, operator
classes, and specialized indexes remain visible and reviewable.

The connection URL is read from `INVOICE_TRIAGE_DATABASE_URL`; it is never
stored in Alembic configuration. For the local Compose database, the easiest
command is:

```bash
docker compose --profile tools run --rm migrate
```

To run Alembic from an activated host environment whose variables are already
exported:

```bash
python -m alembic upgrade head
python -m alembic current
python -m alembic history
```

Autogeneration is intentionally disabled. New revisions should be reviewed and
written explicitly for PostgreSQL and Amazon RDS compatibility.

Current head: `0006_invoice_records`.
