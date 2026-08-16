# Pipeline Status Glossary

InvoiceFlow separates **metadata quality**, **workflow status**, and **buyer verdict**. UI labels must reflect the same semantics as backend gates.

## Stage 1 — Extraction & routing

| Field | Meaning |
|-------|---------|
| `extraction_quality` | Metadata: `extraction_complete`, `extraction_partial`, `extraction_weak`, `extraction_failed`. Optional missing fields (PO ref, line items) do **not** downgrade quality alone. |
| `status` | Workflow gate: `stage1_passed`, `needs_human_review`, or `extraction_failed`. Driven by approval-critical fields, verification, reconciliation/arithmetic — not optional match signals. |
| `needs_human_review` | Approval-critical issue, weak extraction, or blocking verification — not merely missing PO reference. |

## Stage 2 — PO matching

| Status | Meaning |
|--------|---------|
| `matched` / `high_confidence_match` | PO selected with sufficient evidence; Stages 3–5 may run (subject to contract gate). |
| `suggested_po_match` | **No PO on invoice** — ranked suggestions only; human confirm required before full validation. |
| `waiting_for_po` | **PO printed on invoice** but not found in master data. |
| `ambiguous_match` / `multiple_candidates` | More than one viable PO; human must choose. |
| `non_po_workflow` | Non-PO spend path; limited Stage 3 validation when contract gate allows. |
| `unmatched` / `no_matching_evidence` | No viable candidates or insufficient extraction for matching. |
| `po_suggestions_rejected` | Human rejected suggestions; awaiting manual PO or correction. |

### Auto-match (no-PO)

When `vendor_amount_no_po_auto_match` policy passes — single open PO for vendor, exact vendor match, amount within remaining balance — status becomes `high_confidence_match` without line coverage.

## Stage 3 — Contract gate

Stage 3 runs only when `validate_contract()` returns `is_valid` with `validation_mode` of `full` or `limited`.

Blocked when:

- `suggestion_mode` with unconfirmed suggestion provenance
- `suggested_po_match`, `ambiguous_match`, `multiple_candidates` (until human confirms)

## Stage 4 — Buyer verdict

Evaluate Stage 4 decision (`AUTO_APPROVED`, `APPROVE`, holds) **before** inferring verdict from Stage 1 `needs_human_review`.

## Import & PO master (unified)

| Store | Role |
|-------|------|
| `purchase_orders` + `vendors` | **Single PO master** for Stage 2 — includes developer seed **and** user CSV rows mirrored on import |
| `source_records` | Audit copy of imported invoice/transaction rows (lineage only) |

On import activate, every invoice transaction row is mirrored into `purchase_orders` with:
- `po_number` = CSV PO column if present, else `IMP-{source_record_id}`
- `total_amount` = CSV invoice total (blanket open PO)
- `metadata.import_derived = true` for user uploads

**PO on invoice is not required.** Matching uses vendor, amount, and invoice identity against the unified PO master.

Run `python scripts/sync_source_records_to_po_master.py` to backfill existing `source_records` into `purchase_orders`.

Full demo reset (invoice history + upload master): `python scripts/reset_demo_environment.py`

## Stage 2 vendor vs duplicate (common confusion)

| Signal | Meaning |
|--------|---------|
| `vendor_master_status: master_hit` | Invoice vendor name resolved to a row in `vendors` |
| `vendor_master_status: po_aligned` | Vendor ID taken from matched PO (name equivalent; OCR comma variants OK) |
| Items needing attention "vendor mismatch" | Only when vendor is truly unresolved **and** PO match did not align vendor |
| CSV in `source_records` / `purchase_orders` | PO **matching** master only — does not mark an invoice image as "already paid" |
| Duplicate detection | Compares **invoice_runs** (processed invoice submissions), not CSV rows |

Duplicate blocking applies only when a **prior run was approved or allocated** (`APPROVE`, `AUTO_APPROVED`, `APPROVAL_REQUIRED`, or posted allocation). Failed/rejected re-test runs (`REJECT`, `TERMINAL_REJECT`, Stage 3 `BLOCKED`) are ignored so development re-uploads do not false-block.

Import-mirrored blanket POs (`metadata.import_derived`) without PO tax terms use **consistency-only** tax validation (subtotal + tax = total), not a fixed statutory rate.

## Import API flags

| Flag | Meaning |
|------|---------|
| `review_needed` | Ambiguous column mappings — commit blocked (HTTP 422) until `/import/confirm`. |
| `partial_success` | Some row types imported; UI may enable import when no blocked rows and not `review_needed`. |
