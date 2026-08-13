"""Synchronous PostgreSQL connection pooling and pgvector registration."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from invoice_triage.config import AppSettings


def _configure_connection(connection: Connection[Any]) -> None:
    """Register pgvector codecs on every newly opened pooled connection."""

    register_vector(connection)
    # Type discovery uses a query. Pool callbacks must return connections in an
    # idle state, so close that read-only transaction before the connection is
    # handed to application code.
    connection.commit()


class Database:
    """Own the application's synchronous PostgreSQL connection pool.

    Constructing the object does not perform network I/O. Call :meth:`open`
    during application startup and :meth:`close` during shutdown.
    """

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 5,
        timeout: float = 30.0,
    ) -> None:
        if min_size < 0:
            raise ValueError("min_size cannot be negative")
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        if min_size > max_size:
            raise ValueError("min_size cannot exceed max_size")

        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            open=False,
            kwargs={"row_factory": dict_row},
            configure=_configure_connection,
            check=ConnectionPool.check_connection,
            name="invoice-triage",
        )

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        min_size: int = 1,
        max_size: int = 5,
        timeout: float = 30.0,
    ) -> Database:
        """Create a closed pool without exposing the secret URL in logs."""

        return cls(
            settings.database_url.get_secret_value(),
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
        )

    def open(self, *, wait: bool = True, timeout: float = 30.0) -> None:
        """Open the pool and optionally wait for its minimum connections."""

        self._pool.open(wait=wait, timeout=timeout)

    def close(self, *, timeout: float = 5.0) -> None:
        """Stop accepting work and close all pooled connections."""

        self._pool.close(timeout=timeout)

    @contextmanager
    def connection(self) -> Iterator[Connection[dict[str, Any]]]:
        """Yield a transactional connection and return it safely to the pool."""

        with self._pool.connection() as connection:
            yield connection

    def check_health(self) -> bool:
        """Verify that a pooled connection can execute a trivial query."""

        with self.connection() as connection:
            row = connection.execute("SELECT 1 AS healthy").fetchone()
        return row is not None and row["healthy"] == 1

    def __enter__(self) -> Database:
        self.open()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
