# AP Invoice Triage Synthetic Corpus

This directory contains fictional records for developing and evaluating the AP
Invoice Triage Agent. No organization, person, address, telephone number,
contract, invoice, or remittance reference in this corpus is real.

## Directory map

- `vendors/vendors.csv` is the structured vendor-master fixture used by
  `lookup_vendor`.
- `budgets/monthly_budgets.csv` is the structured budget fixture used by
  `check_budget`.
- `contracts/` contains one Markdown contract per vendor. These documents are
  part of the retrieval corpus.
- `policies/` contains one category policy per vendor category. Each policy has
  12 heading-delimited clauses intended to become independently retrievable
  chunks.
- `invoices/` contains 20 Markdown invoices used as persisted transaction inputs
  to the triage agent. Twelve historical records are `committed`; eight
  candidates are `pending_review`.
- `evaluation/expected_findings.csv` contains ground-truth invoice outcomes.
- `evaluation/retrieval_queries.jsonl` contains labeled retrieval queries for
  comparing vector, lexical, hybrid, and later reranked search. Its 50 labels
  include 20 adversarial exact-match cases grouped by invoice number, clause
  ID, acronym, vendor alias, and dollar amount.

## Source-of-truth order

1. Resolve identity and operational status from the vendor master.
2. Validate vendor-specific prices and terms against the applicable contract.
3. Apply the relevant category policy and company budget record.
4. Escalate conflicts, missing evidence, suspected duplicates, inactive
   vendors, and remittance changes to a human reviewer.
5. Never use a model recommendation as authority to approve or issue payment.

## Ingestion boundaries

Embed and index `contracts/` and `policies/` for RAG. Load the vendor master,
budgets, and normalized invoices into structured storage instead of embedding
them. Treat invoices as transaction inputs, not grounding documents. Never expose the files under
`evaluation/` to the running agent; they are test labels.

Preserve YAML front matter as document metadata. Chunk Markdown at second-level
headings, and keep each table with the heading and paragraph that introduce it.

## Synthetic-data safety

All email addresses use the reserved `.example` domain. Telephone numbers use
the fictional North American `555-01xx` range. Remittance values are opaque
references; no banking data, credentials, tax identifiers, or personal data are
stored in this repository.
