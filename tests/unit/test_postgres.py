"""Unit tests for PostgreSQL pool configuration without network access."""

import pytest

from invoice_triage.config import AppSettings
from invoice_triage.storage.postgres import Database


def test_database_can_be_constructed_from_secret_settings() -> None:
    settings = AppSettings(
        database_url="postgresql://app:secret@localhost:5432/invoice_triage"
    )

    database = Database.from_settings(settings, min_size=0, max_size=2)

    # Construction is deliberately lazy and therefore needs no running server.
    database.close()


@pytest.mark.parametrize(
    ("min_size", "max_size", "message"),
    [
        (-1, 1, "min_size cannot be negative"),
        (0, 0, "max_size must be at least 1"),
        (2, 1, "min_size cannot exceed max_size"),
    ],
)
def test_database_rejects_invalid_pool_sizes(
    min_size: int,
    max_size: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Database(
            "postgresql://app:secret@localhost:5432/invoice_triage",
            min_size=min_size,
            max_size=max_size,
        )
