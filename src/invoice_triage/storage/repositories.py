"""Explicit PostgreSQL repositories for structured operational data."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
import hashlib
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from invoice_triage.domain import (
    DocumentChunk,
    DuplicateReason,
    InvoiceDuplicateMatch,
    InvoiceIdentifier,
    MonthlyBudget,
    PersistedInvoice,
    SourceDocument,
    Vendor,
    VendorContact,
)


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


class InvoiceRepository:
    """Persist normalized invoices and perform deterministic operational checks."""

    _SHIPMENT_IDENTIFIER_TYPES = (
        "bill_of_lading",
        "tracking_number",
        "packing_slip",
        "proof_of_delivery",
    )

    def upsert_many(
        self,
        connection: Connection[dict[str, Any]],
        invoices: Sequence[PersistedInvoice],
    ) -> tuple[int, int]:
        """Atomically replace invoice records and their typed identifiers."""

        if not invoices:
            return 0, 0
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO invoice_records (
                    invoice_id,
                    vendor_invoice_number,
                    vendor_id,
                    invoice_date,
                    received_at,
                    currency,
                    total_due,
                    cost_center,
                    record_status,
                    service_period_start,
                    service_period_end,
                    source_path,
                    content_hash
                ) VALUES (
                    %(invoice_id)s,
                    %(vendor_invoice_number)s,
                    %(vendor_id)s,
                    %(invoice_date)s,
                    %(received_at)s,
                    %(currency)s,
                    %(total_due)s,
                    %(cost_center)s,
                    %(record_status)s,
                    %(service_period_start)s,
                    %(service_period_end)s,
                    %(source_path)s,
                    %(content_hash)s
                )
                ON CONFLICT (invoice_id) DO UPDATE SET
                    vendor_invoice_number = EXCLUDED.vendor_invoice_number,
                    vendor_id = EXCLUDED.vendor_id,
                    invoice_date = EXCLUDED.invoice_date,
                    received_at = EXCLUDED.received_at,
                    currency = EXCLUDED.currency,
                    total_due = EXCLUDED.total_due,
                    cost_center = EXCLUDED.cost_center,
                    record_status = EXCLUDED.record_status,
                    service_period_start = EXCLUDED.service_period_start,
                    service_period_end = EXCLUDED.service_period_end,
                    source_path = EXCLUDED.source_path,
                    content_hash = EXCLUDED.content_hash,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [self._parameters(invoice) for invoice in invoices],
            )

        invoice_ids = [invoice.invoice_id for invoice in invoices]
        connection.execute(
            "DELETE FROM invoice_identifiers WHERE invoice_id = ANY(%s)",
            (invoice_ids,),
        )
        identifier_rows = [
            {
                "invoice_id": invoice.invoice_id,
                "identifier_type": identifier.identifier_type.value,
                "identifier_value": identifier.value,
            }
            for invoice in invoices
            for identifier in invoice.identifiers
        ]
        if identifier_rows:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO invoice_identifiers (
                        invoice_id,
                        identifier_type,
                        identifier_value
                    ) VALUES (
                        %(invoice_id)s,
                        %(identifier_type)s,
                        %(identifier_value)s
                    )
                    """,
                    identifier_rows,
                )
        return len(invoices), len(identifier_rows)

    def get_by_id(
        self,
        connection: Connection[dict[str, Any]],
        invoice_id: str,
    ) -> PersistedInvoice | None:
        row = connection.execute(
            "SELECT * FROM invoice_records WHERE invoice_id = %s",
            (invoice_id,),
        ).fetchone()
        if row is None:
            return None
        return self._from_row(row, self._identifiers(connection, invoice_id))

    def find_duplicate_matches(
        self,
        connection: Connection[dict[str, Any]],
        candidate: PersistedInvoice,
    ) -> tuple[InvoiceDuplicateMatch, ...]:
        """Find earlier active records sharing an exact duplicate signal."""

        rows = connection.execute(
            """
            SELECT
                other.*,
                (
                    other.vendor_id = %(vendor_id)s
                    AND lower(other.vendor_invoice_number) =
                        lower(%(vendor_invoice_number)s)
                ) AS vendor_number_match,
                (
                    %(service_period_start)s::date IS NOT NULL
                    AND other.vendor_id = %(vendor_id)s
                    AND other.currency = %(currency)s
                    AND other.total_due = %(total_due)s
                    AND other.service_period_start = %(service_period_start)s::date
                    AND other.service_period_end = %(service_period_end)s::date
                ) AS service_amount_match
            FROM invoice_records AS other
            WHERE other.invoice_id <> %(invoice_id)s
              AND other.record_status IN ('pending_review', 'committed')
              AND (
                    other.received_at < %(received_at)s
                    OR (
                        other.received_at = %(received_at)s
                        AND other.invoice_id < %(invoice_id)s
                    )
              )
              AND (
                    (
                        other.vendor_id = %(vendor_id)s
                        AND lower(other.vendor_invoice_number) =
                            lower(%(vendor_invoice_number)s)
                    )
                    OR (
                        %(service_period_start)s::date IS NOT NULL
                        AND other.vendor_id = %(vendor_id)s
                        AND other.currency = %(currency)s
                        AND other.total_due = %(total_due)s
                        AND other.service_period_start =
                            %(service_period_start)s::date
                        AND other.service_period_end = %(service_period_end)s::date
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM invoice_identifiers AS candidate_identifier
                        JOIN invoice_identifiers AS other_identifier
                          ON other_identifier.identifier_type =
                                candidate_identifier.identifier_type
                         AND lower(other_identifier.identifier_value) =
                                lower(candidate_identifier.identifier_value)
                        WHERE candidate_identifier.invoice_id = %(invoice_id)s
                          AND other_identifier.invoice_id = other.invoice_id
                          AND candidate_identifier.identifier_type = ANY(
                                %(shipment_identifier_types)s::text[]
                          )
                    )
              )
            ORDER BY other.received_at, other.invoice_id
            """,
            {
                **self._parameters(candidate),
                "shipment_identifier_types": list(self._SHIPMENT_IDENTIFIER_TYPES),
            },
        ).fetchall()

        matches: list[InvoiceDuplicateMatch] = []
        for row in rows:
            matched_identifiers = self._shared_shipment_identifiers(
                connection,
                candidate.invoice_id,
                row["invoice_id"],
            )
            reasons: list[DuplicateReason] = []
            if row["vendor_number_match"]:
                reasons.append(DuplicateReason.VENDOR_INVOICE_NUMBER)
            if row["service_amount_match"]:
                reasons.append(DuplicateReason.SERVICE_PERIOD_AMOUNT)
            if matched_identifiers:
                reasons.append(DuplicateReason.SHIPMENT_IDENTIFIER)
            matches.append(
                InvoiceDuplicateMatch(
                    invoice=self._from_row(
                        row,
                        self._identifiers(connection, row["invoice_id"]),
                    ),
                    reasons=tuple(reasons),
                    matched_identifiers=matched_identifiers,
                )
            )
        return tuple(matches)

    def sum_committed_for_budget(
        self,
        connection: Connection[dict[str, Any]],
        *,
        budget_period: date,
        category: str,
        cost_center: str,
        currency: str,
        exclude_invoice_id: str | None = None,
    ) -> Decimal:
        """Sum persisted committed invoices in one monthly budget scope."""

        row = connection.execute(
            """
            SELECT COALESCE(sum(invoice.total_due), 0) AS committed_total
            FROM invoice_records AS invoice
            JOIN vendors AS vendor ON vendor.vendor_id = invoice.vendor_id
            WHERE invoice.record_status = 'committed'
              AND invoice.invoice_date >= %(budget_period)s
              AND invoice.invoice_date < %(budget_period)s + INTERVAL '1 month'
              AND vendor.category = %(category)s
              AND invoice.cost_center = %(cost_center)s
              AND invoice.currency = %(currency)s
              AND (
                    %(exclude)s::text IS NULL
                    OR invoice.invoice_id <> %(exclude)s
              )
            """,
            {
                "budget_period": budget_period,
                "category": category,
                "cost_center": cost_center,
                "currency": currency,
                "exclude": exclude_invoice_id,
            },
        ).fetchone()
        assert row is not None
        return Decimal(row["committed_total"])

    def count(self, connection: Connection[dict[str, Any]]) -> int:
        row = connection.execute(
            "SELECT count(*) AS count FROM invoice_records"
        ).fetchone()
        assert row is not None
        return row["count"]

    @staticmethod
    def _parameters(invoice: PersistedInvoice) -> dict[str, Any]:
        return {
            "invoice_id": invoice.invoice_id,
            "vendor_invoice_number": invoice.vendor_invoice_number,
            "vendor_id": invoice.vendor_id,
            "invoice_date": invoice.invoice_date,
            "received_at": invoice.received_at,
            "currency": invoice.currency,
            "total_due": invoice.total_due,
            "cost_center": invoice.cost_center,
            "record_status": invoice.record_status.value,
            "service_period_start": invoice.service_period_start,
            "service_period_end": invoice.service_period_end,
            "source_path": invoice.source_path,
            "content_hash": invoice.content_hash,
        }

    @staticmethod
    def _from_row(
        row: dict[str, Any],
        identifiers: tuple[InvoiceIdentifier, ...],
    ) -> PersistedInvoice:
        return PersistedInvoice(
            invoice_id=row["invoice_id"],
            vendor_invoice_number=row["vendor_invoice_number"],
            vendor_id=row["vendor_id"],
            invoice_date=row["invoice_date"],
            received_at=row["received_at"],
            currency=row["currency"],
            total_due=row["total_due"],
            cost_center=row["cost_center"],
            record_status=row["record_status"],
            service_period_start=row["service_period_start"],
            service_period_end=row["service_period_end"],
            identifiers=identifiers,
            source_path=row["source_path"],
            content_hash=row["content_hash"],
        )

    @staticmethod
    def _identifiers(
        connection: Connection[dict[str, Any]],
        invoice_id: str,
    ) -> tuple[InvoiceIdentifier, ...]:
        rows = connection.execute(
            """
            SELECT identifier_type, identifier_value
            FROM invoice_identifiers
            WHERE invoice_id = %s
            ORDER BY identifier_type, identifier_value
            """,
            (invoice_id,),
        ).fetchall()
        return tuple(
            InvoiceIdentifier(
                identifier_type=row["identifier_type"],
                value=row["identifier_value"],
            )
            for row in rows
        )

    def _shared_shipment_identifiers(
        self,
        connection: Connection[dict[str, Any]],
        candidate_invoice_id: str,
        other_invoice_id: str,
    ) -> tuple[InvoiceIdentifier, ...]:
        rows = connection.execute(
            """
            SELECT
                candidate.identifier_type,
                candidate.identifier_value
            FROM invoice_identifiers AS candidate
            JOIN invoice_identifiers AS other
              ON other.identifier_type = candidate.identifier_type
             AND lower(other.identifier_value) = lower(candidate.identifier_value)
            WHERE candidate.invoice_id = %s
              AND other.invoice_id = %s
              AND candidate.identifier_type = ANY(%s::text[])
            ORDER BY candidate.identifier_type, candidate.identifier_value
            """,
            (
                candidate_invoice_id,
                other_invoice_id,
                list(self._SHIPMENT_IDENTIFIER_TYPES),
            ),
        ).fetchall()
        return tuple(
            InvoiceIdentifier(
                identifier_type=row["identifier_type"],
                value=row["identifier_value"],
            )
            for row in rows
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
