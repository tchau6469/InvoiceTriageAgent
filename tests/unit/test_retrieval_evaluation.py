"""Tests for strict relevance-label loading."""

from pathlib import Path

from invoice_triage.evaluation import read_retrieval_labels
from invoice_triage.ingestion import read_vendor_fixtures


PROJECT_ROOT = Path(__file__).parents[2]


def test_retrieval_labels_are_complete_and_mark_historical_query() -> None:
    labels = read_retrieval_labels(
        PROJECT_ROOT / "fixtures/evaluation/retrieval_queries.jsonl"
    )

    assert len(labels) == 50
    assert len({label.query_id for label in labels}) == 50
    historical = next(label for label in labels if label.query_id == "RQ-016")
    assert historical.as_of_date.isoformat() == "2025-09-30"
    assert historical.expected_doc_id == "CTR-VND-1010-2025"

    adversarial = [label for label in labels if label.challenge is not None]
    assert len(adversarial) == 20
    challenge_counts: dict[str, int] = {}
    for label in adversarial:
        challenge_counts[label.challenge.value] = (
            challenge_counts.get(label.challenge.value, 0) + 1
        )
    assert set(challenge_counts.values()) == {4}

    invoice_labels = [
        label for label in adversarial if label.challenge.value == "invoice_number"
    ]
    assert all(label.source_invoice_id for label in invoice_labels)
    assert all(label.vendor_id for label in invoice_labels)
    assert all(
        (PROJECT_ROOT / "fixtures/invoices" / f"{label.source_invoice_id}.md").is_file()
        for label in invoice_labels
    )
    for label in invoice_labels:
        invoice_path = (
            PROJECT_ROOT / "fixtures/invoices" / f"{label.source_invoice_id}.md"
        )
        fields = {
            key: value.strip()
            for line in invoice_path.read_text(encoding="utf-8").splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        assert fields["vendor_id"] == label.vendor_id
        assert fields["vendor_invoice_number"] in label.query

    vendors = {
        vendor.vendor_id: vendor
        for vendor in read_vendor_fixtures(
            PROJECT_ROOT / "fixtures/vendors/vendors.csv"
        )
    }
    alias_labels = [
        label for label in adversarial if label.challenge.value == "vendor_alias"
    ]
    for label in alias_labels:
        vendor = vendors[label.vendor_id]
        assert any(alias.casefold() in label.query.casefold() for alias in vendor.aliases)
