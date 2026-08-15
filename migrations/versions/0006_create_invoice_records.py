"""Create normalized invoice persistence and identifier tables.

Revision ID: 0006_invoice_records
Revises: 0005_title_search
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0006_invoice_records"
down_revision: str | None = "0005_title_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE invoice_records (
            invoice_id TEXT PRIMARY KEY,
            vendor_invoice_number TEXT NOT NULL,
            vendor_id TEXT NOT NULL REFERENCES vendors(vendor_id),
            invoice_date DATE NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
            total_due NUMERIC(14, 2) NOT NULL CHECK (total_due >= 0),
            cost_center TEXT NOT NULL,
            record_status TEXT NOT NULL CHECK (
                record_status IN (
                    'pending_review',
                    'committed',
                    'rejected',
                    'voided'
                )
            ),
            service_period_start DATE,
            service_period_end DATE,
            source_path TEXT NOT NULL UNIQUE,
            content_hash CHAR(64) NOT NULL CHECK (
                content_hash ~ '^[0-9a-f]{64}$'
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (
                (service_period_start IS NULL) = (service_period_end IS NULL)
            ),
            CHECK (
                service_period_end IS NULL
                OR service_period_end >= service_period_start
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE invoice_identifiers (
            invoice_id TEXT NOT NULL
                REFERENCES invoice_records(invoice_id) ON DELETE CASCADE,
            identifier_type TEXT NOT NULL CHECK (
                identifier_type IN (
                    'bill_of_lading',
                    'tracking_number',
                    'packing_slip',
                    'proof_of_delivery',
                    'purchase_order'
                )
            ),
            identifier_value TEXT NOT NULL,
            PRIMARY KEY (invoice_id, identifier_type, identifier_value)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_invoice_records_vendor_number
        ON invoice_records (vendor_id, lower(vendor_invoice_number))
        WHERE record_status IN ('pending_review', 'committed')
        """
    )
    op.execute(
        """
        CREATE INDEX ix_invoice_records_service_amount
        ON invoice_records (
            vendor_id,
            currency,
            total_due,
            service_period_start,
            service_period_end
        )
        WHERE record_status IN ('pending_review', 'committed')
          AND service_period_start IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_invoice_records_budget_commitments
        ON invoice_records (invoice_date, cost_center, currency)
        INCLUDE (vendor_id, total_due)
        WHERE record_status = 'committed'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_invoice_records_received_at
        ON invoice_records (received_at, invoice_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_invoice_identifiers_lookup
        ON invoice_identifiers (identifier_type, lower(identifier_value))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoice_identifiers")
    op.execute("DROP TABLE IF EXISTS invoice_records")
