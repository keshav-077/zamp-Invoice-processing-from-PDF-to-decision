# AP Policy — Demo Assumptions (InvoiceFlow AI)

Plain-English rules used for the Zamp PS-1 demo. State these in the 5-minute video.

## Matching rules

- **Match key:** Invoice PO reference → PO number in procurement system (not invoice number on PO).
- **Header match is enough:** Vendor + PO number + total within tolerance can match even when line descriptions differ.
- **Line match is optional:** Bundled or summary invoices may not line-match; that does not auto-reject.

## Auto-approve (system)

Auto-approve when **all** of the following are true:

1. Extraction and verification pass (Stage 1 `stage1_passed`) — missing optional PO reference alone does **not** fail Stage 1
2. PO matched with high confidence (exact PO on invoice preferred, or policy-approved vendor+amount no-PO match)
3. All validation controls pass (Stage 3 `VALIDATED`) — duplicates, vendor active, tax self-consistent, budget OK
4. Invoice total **≤ $5,000**

## Manual review required

Route to AP review when:

- Invoice number or other **approval-critical** field missing or low confidence (optional PO reference is metadata only)
- PO ambiguous (two POs score similarly) or suggestions not yet confirmed (`suggested_po_match`)
- Amount variance beyond tolerance vs PO remaining balance
- Arithmetic mismatch (subtotal + tax ≠ total)
- Invoice total **> $5,000** (needs approver regardless of match quality)
- Crumpled scan with uncertain extraction

## Reject / block

- Duplicate invoice confirmed (same vendor + invoice number + amount already processed)
- Vendor suspended or blacklisted
- Terminal validation failure

## Tolerances (demo)

| Check | Tolerance |
|-------|-----------|
| Price vs PO line | 2% |
| Quantity | 5% |
| Tax rate | Uses rate inferred from invoice document (self-consistent) |
| PO budget remaining | 5% |
| Auto-approve amount cap | $5,000 |

## PO types

- **`blanket`:** Services / summary invoices — 2-way match (PO + invoice), no GRN required
- **`standard`:** Goods — 3-way match when GRN record exists in system

## Assumptions documented for interview

1. Buyer company is the **Bill To** party; vendors on invoices are suppliers we pay.
2. PO numbers on invoices are authoritative; we seeded PO master to align with extracted PO refs.
3. Historical scans (1980s–90s) demonstrate messy real-world inputs; modern invoices (d8–d15) demonstrate current AP edge cases.
4. Non-PO receipts (restaurant d16, d17) route to non-PO workflow — no PO match expected.
