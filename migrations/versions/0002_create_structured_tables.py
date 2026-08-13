"""Create structured vendor and budget tables.

Revision ID: 0002_structured_tables
Revises: 0001_enable_extensions
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0002_structured_tables"
down_revision: str | None = "0001_enable_extensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORIES = """
    'cloud_software',
    'office_supplies',
    'facilities_maintenance',
    'professional_services',
    'logistics_freight',
    'marketing_events'
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE vendors (
            vendor_id TEXT PRIMARY KEY,
            legal_name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            aliases TEXT[] NOT NULL DEFAULT '{{}}'::TEXT[],
            status TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
            category TEXT NOT NULL CHECK (category IN ({CATEGORIES})),
            historical_spend_12m NUMERIC(14, 2) NOT NULL
                CHECK (historical_spend_12m >= 0),
            currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{{3}}$'),
            default_payment_terms TEXT NOT NULL
                CHECK (default_payment_terms IN ('NET_15', 'NET_30', 'NET_45')),
            default_cost_center TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            contact_title TEXT NOT NULL,
            contact_email TEXT NOT NULL,
            contact_phone TEXT NOT NULL,
            contract_file TEXT NOT NULL,
            remittance_profile_ref TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE monthly_budgets (
            budget_period DATE NOT NULL
                CHECK (EXTRACT(DAY FROM budget_period) = 1),
            category TEXT NOT NULL CHECK (category IN ({CATEGORIES})),
            cost_center TEXT NOT NULL,
            budget_amount NUMERIC(14, 2) NOT NULL CHECK (budget_amount >= 0),
            committed_amount NUMERIC(14, 2) NOT NULL
                CHECK (committed_amount >= 0),
            currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{{3}}$'),
            owner TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (budget_period, category, cost_center),
            CHECK (committed_amount <= budget_amount)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS monthly_budgets")
    op.execute("DROP TABLE IF EXISTS vendors")
