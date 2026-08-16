# Demo Matrix — PS-1 Submission (strict expectations)

Five primary scenarios with **exact** expected outcomes for CI and interview demos.

```bash
python scripts/reset_db.py
python scripts/generate_split_billing_pdfs.py
python scripts/build_po_xlsx.py && python scripts/reset_db.py
python scripts/verify_demo_matrix.py --offline
python scripts/verify_demo_matrix.py              # full LLM pipeline
python scripts/verify_demo_matrix.py --duplicate  # includes duplicate block test
```

## Five primary demo scenarios

| # | File | Scenario | PO | Expected Stage 2 | Expected Stage 3 | Expected Stage 4 | Buyer verdict |
|---|------|----------|-----|------------------|------------------|------------------|---------------|
| 1 | `d2.jpg` | Happy path — explicit PO on invoice | `34313` | `matched` or `high_confidence_match` | `VALIDATED` | `AUTO_APPROVED` or `APPROVAL_REQUIRED` | **Pay** (at $5k policy limit) |
| 2 | `d8.jpg` | Ambiguous PO — no PO on invoice | `PO-8801` / `PO-8802` | `ambiguous_match` | `VALIDATED` or `HOLD` | `REVIEW_REQUIRED` | **Needs review** — confirm PO |
| 3 | `d14.jpg` | Arithmetic mismatch | `PO-9014` | any match state | `HOLD` | `REVIEW_REQUIRED` | **Needs review** — lines ≠ total |
| 4 | `split_billing_part2.pdf` | Split billing — 2nd invoice vs remaining PO balance | `PO-SPLIT-01` | `matched` or `high_confidence_match` | `VALIDATED` | `APPROVAL_REQUIRED` or `AUTO_APPROVED` | **Pay** after balance check ($3,500 vs $6,000 remaining) |
| 5 | `d9.jpg` (×2) | Duplicate protection | `PO-9009` | blocked on 2nd submit | — | `TERMINAL_REJECT` or duplicate HOLD | **Do not pay** — duplicate |
| 6 | `rogers_crumpled.png` | **Your crumpled upload** — Rogers vendor match | `PO-ROGERS-01` | `matched` or `high_confidence_match` | `VALIDATED` | `AUTO_APPROVED` | **Pay** — $300.46 |

### Rogers crumpled demo (recommended live upload)

1. Re-seed DB after `python scripts/build_po_xlsx.py && python scripts/reset_db.py`
2. Upload `test_invoices/dataset/rogers_crumpled.png`
3. No PO printed on invoice — system matches by vendor **Rogers, Smith and Hobbs** + **$300.46** + 7 line items → **PO-ROGERS-01**
4. Tax validated at **19.3%** (vendor rate in `config/validation_policy.yaml`)

### Split billing flow

1. Upload `split_billing_part1.pdf` — consumes $4,000 of PO-SPLIT-01 (PO updated to `previously_invoiced=4000`).
2. Upload `split_billing_part2.pdf` — validates $3,500 against $6,000 remaining.

### Duplicate flow

1. Upload `d9.jpg` — normal processing.
2. Re-upload same file — Stage 3 duplicate detection blocks second submission.

## Secondary scenarios

| File | Role |
|------|------|
| `d9.jpg` | Small auto-approve under $5k |
| `d11.jpg` | Crumpled scan quality |
| `rogers_crumpled.png` | **Primary crumpled demo — upload this** |
| `rogers_clean.png` | Clean reference scan (invoice #229655) |
| `d13.jpg` | Split PO with prior consumption in seed data |

## PO master

- **File:** [`data/PO.xlsx`](data/PO.xlsx)
- **Rebuild:** `python scripts/build_po_xlsx.py`
- **Seed:** `python scripts/reset_db.py`

## 5-minute interview script

1. **Problem** (30s): Manual PO matching is slow and error-prone.
2. **Happy path** (90s): Upload `d2.jpg` → buyer banner shows Pay → stage evidence.
3. **Edge cases** (2 min): `d14.jpg` (math error) + `d8.jpg` (ambiguous PO confirmation).
4. **Split + duplicate** (1 min): Show split billing part 2 + duplicate block on re-upload.
5. **Architecture** (30s): Vercel SPA + Blob upload + Inngest jobs + Neon Postgres.
