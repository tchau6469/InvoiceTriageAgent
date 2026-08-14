"""Explicit PostgreSQL repositories for structured operational data."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
import hashlib
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoice_triage.domain import DocumentChunk, MonthlyBudget, SourceDocument, Vendor, VendorContact


class VendorRepository:
    """Store and retrieve authoritative vendor-master records."""

    def upsert_many(
        self,
        connection: Connection[dict[str, Any]],
        vendors: Sequence[Vendor],
    ) -> int:
        """Insert or replace vendors by stable vendor ID."""

        if not vendors:
            return 0

        with connection.cursor() as cursor:
            cursor.executemany(
                """
            INSERT INTO vendors (
                vendor_id,
                legal_name,
                display_name,
                aliases,
                status,
                category,
                historical_spend_12m,
                currency,
                default_payment_terms,
                default_cost_center,
                contact_name,
                contact_title,
                contact_email,
                contact_phone,
                contract_file,
                remittance_profile_ref
            ) VALUES (
                %(vendor_id)s,
                %(legal_name)s,
                %(display_name)s,
                %(aliases)s,
                %(status)s,
                %(category)s,
                %(historical_spend_12m)s,
                %(currency)s,
                %(default_payment_terms)s,
                %(default_cost_center)s,
                %(contact_name)s,
                %(contact_title)s,
                %(contact_email)s,
                %(contact_phone)s,
                %(contract_file)s,
                %(remittance_profile_ref)s
            )
            ON CONFLICT (vendor_id) DO UPDATE SET
                legal_name = EXCLUDED.legal_name,
                display_name = EXCLUDED.display_name,
                aliases = EXCLUDED.aliases,
                status = EXCLUDED.status,
                category = EXCLUDED.category,
                historical_spend_12m = EXCLUDED.historical_spend_12m,
                currency = EXCLUDED.currency,
                default_payment_terms = EXCLUDED.default_payment_terms,
                default_cost_center = EXCLUDED.default_cost_center,
                contact_name = EXCLUDED.contact_name,
                contact_title = EXCLUDED.contact_title,
                contact_email = EXCLUDED.contact_email,
                contact_phone = EXCLUDED.contact_phone,
                contract_file = EXCLUDED.contract_file,
                remittance_profile_ref = EXCLUDED.remittance_profile_ref,
                updated_at = CURRENT_TIMESTAMP
                """,
                [self._parameters(vendor) for vendor in vendors],
            )
        return len(vendors)

    def get_by_id(
        self,
        connection: Connection[dict[str, Any]],
        vendor_id: str,
    ) -> Vendor | None:
        """Look up a vendor by its exact stable ID."""

        row = connection.execute(
            "SELECT * FROM vendors WHERE vendor_id = %s",
            (vendor_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def find_by_name_or_alias(
        self,
        connection: Connection[dict[str, Any]],
        name: str,
    ) -> tuple[Vendor, ...]:
        """Resolve legal names, display names, and aliases case-insensitively."""

        rows = connection.execute(
            """
            SELECT *
            FROM vendors
            WHERE lower(legal_name) = lower(%s)
               OR lower(display_name) = lower(%s)
               OR EXISTS (
                    SELECT 1
                    FROM unnest(aliases) AS alias
                    WHERE lower(alias) = lower(%s)
               )
            ORDER BY vendor_id
            """,
            (name, name, name),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def count(self, connection: Connection[dict[str, Any]]) -> int:
        """Return the number of vendor-master records."""

        row = connection.execute("SELECT count(*) AS count FROM vendors").fetchone()
        assert row is not None
        return row["count"]

    @staticmethod
    def _parameters(vendor: Vendor) -> dict[str, Any]:
        return {
            "vendor_id": vendor.vendor_id,
            "legal_name": vendor.legal_name,
            "display_name": vendor.display_name,
            "aliases": list(vendor.aliases),
            "status": vendor.status.value,
            "category": vendor.category.value,
            "historical_spend_12m": vendor.historical_spend_12m,
            "currency": vendor.currency,
            "default_payment_terms": vendor.default_payment_terms.value,
            "default_cost_center": vendor.default_cost_center,
            "contact_name": vendor.contact.name,
            "contact_title": vendor.contact.title,
            "contact_email": vendor.contact.email,
            "contact_phone": vendor.contact.phone,
            "contract_file": vendor.contract_file,
            "remittance_profile_ref": vendor.remittance_profile_ref,
        }

    @staticmethod
    def _from_row(row: dict[str, Any]) -> Vendor:
        return Vendor(
            vendor_id=row["vendor_id"],
            legal_name=row["legal_name"],
            display_name=row["display_name"],
            aliases=tuple(row["aliases"]),
            status=row["status"],
            category=row["category"],
            historical_spend_12m=row["historical_spend_12m"],
            currency=row["currency"],
            default_payment_terms=row["default_payment_terms"],
            default_cost_center=row["default_cost_center"],
            contact=VendorContact(
                name=row["contact_name"],
                title=row["contact_title"],
                email=row["contact_email"],
                phone=row["contact_phone"],
            ),
            contract_file=row["contract_file"],
            remittance_profile_ref=row["remittance_profile_ref"],
        )


class BudgetRepository:
    """Store and retrieve authoritative monthly budget snapshots."""

    def upsert_many(
        self,
        connection: Connection[dict[str, Any]],
        budgets: Sequence[MonthlyBudget],
    ) -> int:
        """Insert or replace budgets by month, category, and cost center."""

        if not budgets:
            return 0

        with connection.cursor() as cursor:
            cursor.executemany(
                """
            INSERT INTO monthly_budgets (
                budget_period,
                category,
                cost_center,
                budget_amount,
                committed_amount,
                currency,
                owner
            ) VALUES (
                %(budget_period)s,
                %(category)s,
                %(cost_center)s,
                %(budget_amount)s,
                %(committed_amount)s,
                %(currency)s,
                %(owner)s
            )
            ON CONFLICT (budget_period, category, cost_center) DO UPDATE SET
                budget_amount = EXCLUDED.budget_amount,
                committed_amount = EXCLUDED.committed_amount,
                currency = EXCLUDED.currency,
                owner = EXCLUDED.owner,
                updated_at = CURRENT_TIMESTAMP
                """,
                [self._parameters(budget) for budget in budgets],
            )
        return len(budgets)

    def get(
        self,
        connection: Connection[dict[str, Any]],
        *,
        budget_period: date,
        category: str,
        cost_center: str,
    ) -> MonthlyBudget | None:
        """Find one budget using its complete business key."""

        row = connection.execute(
            """
            SELECT *
            FROM monthly_budgets
            WHERE budget_period = %s
              AND category = %s
              AND cost_center = %s
            """,
            (budget_period, category, cost_center),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def count(self, connection: Connection[dict[str, Any]]) -> int:
        """Return the number of monthly budget records."""

        row = connection.execute(
            "SELECT count(*) AS count FROM monthly_budgets"
        ).fetchone()
        assert row is not None
        return row["count"]

    @staticmethod
    def _parameters(budget: MonthlyBudget) -> dict[str, Any]:
        return {
            "budget_period": budget.budget_period,
            "category": budget.category.value,
            "cost_center": budget.cost_center,
            "budget_amount": budget.budget_amount,
            "committed_amount": budget.committed_amount,
            "currency": budget.currency,
            "owner": budget.owner,
        }

    @staticmethod
    def _from_row(row: dict[str, Any]) -> MonthlyBudget:
        return MonthlyBudget(
            budget_period=row["budget_period"],
            category=row["category"],
            cost_center=row["cost_center"],
            budget_amount=row["budget_amount"],
            committed_amount=row["committed_amount"],
            currency=row["currency"],
            owner=row["owner"],
        )


class DocumentRepository:
    """Idempotently store parsed grounding documents and their embeddings."""

    def upsert(
        self,
        connection: Connection[dict[str, Any]],
        document: SourceDocument,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> int:
        """Replace one document's current chunk set inside the caller's transaction."""

        if not chunks:
            raise ValueError("a source document must have at least one chunk")
        if len(chunks) != len(embeddings):
            raise ValueError("every document chunk must have exactly one embedding")
        if any(chunk.document_id != document.document_id for chunk in chunks):
            raise ValueError("all chunks must belong to the supplied source document")

        connection.execute(
            """
            INSERT INTO source_documents (
                document_id,
                document_type,
                title,
                content,
                source_path,
                status,
                vendor_id,
                category,
                effective_date,
                expiration_date,
                metadata,
                content_sha256
            ) VALUES (
                %(document_id)s,
                %(document_type)s,
                %(title)s,
                %(content)s,
                %(source_path)s,
                %(status)s,
                %(vendor_id)s,
                %(category)s,
                %(effective_date)s,
                %(expiration_date)s,
                %(metadata)s,
                %(content_sha256)s
            )
            ON CONFLICT (document_id) DO UPDATE SET
                document_type = EXCLUDED.document_type,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                source_path = EXCLUDED.source_path,
                status = EXCLUDED.status,
                vendor_id = EXCLUDED.vendor_id,
                category = EXCLUDED.category,
                effective_date = EXCLUDED.effective_date,
                expiration_date = EXCLUDED.expiration_date,
                metadata = EXCLUDED.metadata,
                content_sha256 = EXCLUDED.content_sha256,
                updated_at = CURRENT_TIMESTAMP
            """,
            self._document_parameters(document),
        )

        parameters = [
            self._chunk_parameters(chunk, embedding)
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        # Move existing ordinals out of the final range first. This allows
        # sections to be reordered without colliding with the table's
        # (document_id, ordinal) uniqueness constraint during the upsert.
        connection.execute(
            """
            UPDATE document_chunks
            SET ordinal = ordinal + 1000000
            WHERE document_id = %s
            """,
            (document.document_id,),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO document_chunks (
                    chunk_id,
                    document_id,
                    document_type,
                    section,
                    ordinal,
                    content,
                    source_path,
                    status,
                    vendor_id,
                    category,
                    effective_date,
                    expiration_date,
                    metadata,
                    content_sha256,
                    embedding
                ) VALUES (
                    %(chunk_id)s,
                    %(document_id)s,
                    %(document_type)s,
                    %(section)s,
                    %(ordinal)s,
                    %(content)s,
                    %(source_path)s,
                    %(status)s,
                    %(vendor_id)s,
                    %(category)s,
                    %(effective_date)s,
                    %(expiration_date)s,
                    %(metadata)s,
                    %(content_sha256)s,
                    %(embedding)s
                )
                ON CONFLICT (chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    document_type = EXCLUDED.document_type,
                    section = EXCLUDED.section,
                    ordinal = EXCLUDED.ordinal,
                    content = EXCLUDED.content,
                    source_path = EXCLUDED.source_path,
                    status = EXCLUDED.status,
                    vendor_id = EXCLUDED.vendor_id,
                    category = EXCLUDED.category,
                    effective_date = EXCLUDED.effective_date,
                    expiration_date = EXCLUDED.expiration_date,
                    metadata = EXCLUDED.metadata,
                    content_sha256 = EXCLUDED.content_sha256,
                    embedding = EXCLUDED.embedding,
                    updated_at = CURRENT_TIMESTAMP
                """,
                parameters,
            )

        connection.execute(
            """
            DELETE FROM document_chunks
            WHERE document_id = %s
              AND NOT (chunk_id = ANY(%s))
            """,
            (document.document_id, [chunk.chunk_id for chunk in chunks]),
        )
        return len(chunks)

    def count_documents(self, connection: Connection[dict[str, Any]]) -> int:
        row = connection.execute(
            "SELECT count(*) AS count FROM source_documents"
        ).fetchone()
        assert row is not None
        return row["count"]

    def count_chunks(self, connection: Connection[dict[str, Any]]) -> int:
        row = connection.execute("SELECT count(*) AS count FROM document_chunks").fetchone()
        assert row is not None
        return row["count"]

    @staticmethod
    def _document_parameters(document: SourceDocument) -> dict[str, Any]:
        return {
            "document_id": document.document_id,
            "document_type": document.document_type.value,
            "title": document.title,
            "content": document.content,
            "source_path": document.source_path,
            "status": document.status.value,
            "vendor_id": document.vendor_id,
            "category": document.category.value if document.category else None,
            "effective_date": document.effective_date,
            "expiration_date": document.expiration_date,
            "metadata": Jsonb(document.metadata),
            "content_sha256": hashlib.sha256(
                document.content.encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _chunk_parameters(
        chunk: DocumentChunk,
        embedding: Sequence[float],
    ) -> dict[str, Any]:
        hash_input = f"{chunk.section}\n{chunk.content}".encode("utf-8")
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "document_type": chunk.document_type.value,
            "section": chunk.section,
            "ordinal": chunk.ordinal,
            "content": chunk.content,
            "source_path": chunk.source_path,
            "status": chunk.status.value,
            "vendor_id": chunk.vendor_id,
            "category": chunk.category.value if chunk.category else None,
            "effective_date": chunk.effective_date,
            "expiration_date": chunk.expiration_date,
            "metadata": Jsonb(chunk.metadata),
            "content_sha256": hashlib.sha256(hash_input).hexdigest(),
            "embedding": list(embedding),
        }
