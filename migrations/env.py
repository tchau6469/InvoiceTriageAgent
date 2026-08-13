"""Alembic environment configured from application settings."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from invoice_triage.config import AppSettings


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Schema changes are explicit; there is deliberately no ORM metadata target.
target_metadata = None


def _sqlalchemy_url() -> str:
    """Translate the application URL to SQLAlchemy's Psycopg 3 dialect."""

    url = AppSettings.from_environment().database_url.get_secret_value()
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    """Render migrations without opening a database connection."""

    context.configure(
        url=_sqlalchemy_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=False,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations through a short-lived, unpooled connection."""

    engine = create_engine(_sqlalchemy_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            _run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
