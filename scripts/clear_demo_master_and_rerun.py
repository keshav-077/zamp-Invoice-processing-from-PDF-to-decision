"""
Remove demo-seeded PO master data (from data/PO.xlsx) and re-run Stage 2–5
for Harrington invoice runs. Keeps source_records from user imports.

Usage (from invoiceflow-ai/):
  python scripts/clear_demo_master_and_rerun.py
  python scripts/clear_demo_master_and_rerun.py --document-id e0fa7af7-282
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import close_db, get_connection, init_db  # noqa: E402
from app.db import repository  # noqa: E402
from app.models.extraction import InvoiceExtraction  # noqa: E402
from app.models.verification import VerificationResult  # noqa: E402
from app.models.reconciliation import ReconciliationResult  # noqa: E402
from app.services.pipeline_rerun_service import rerun_stages_2_through_5  # noqa: E402


def clear_demo_master(company_id: str = "DEFAULT") -> dict:
    """Remove seed PO master only; preserve user-import mirrored POs."""
    conn = get_connection()
    seed_pos = conn.execute(
        """
        SELECT po_number FROM purchase_orders
        WHERE company_id = ?
          AND (metadata_json IS NULL OR metadata_json NOT LIKE '%"import_derived": true%')
        """,
        (company_id,),
    ).fetchall()
    seed_po_numbers = [r[0] for r in seed_pos]

    counts = {"seed_pos_removed": len(seed_po_numbers)}
    for po_number in seed_po_numbers:
        conn.execute(
            "DELETE FROM po_lines WHERE company_id = ? AND po_number = ?",
            (company_id, po_number),
        )
        conn.execute(
            "DELETE FROM grn_records WHERE company_id = ? AND po_number = ?",
            (company_id, po_number),
        )
        conn.execute(
            "DELETE FROM po_references WHERE company_id = ? AND po_number = ?",
            (company_id, po_number),
        )
        conn.execute(
            "DELETE FROM purchase_orders WHERE company_id = ? AND po_number = ?",
            (company_id, po_number),
        )

    # Drop vendors with no remaining PO references
    orphan_vendors = conn.execute(
        """
        SELECT v.vendor_id FROM vendors v
        WHERE v.company_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM purchase_orders p
            WHERE p.company_id = v.company_id AND p.vendor_id = v.vendor_id
          )
        """,
        (company_id,),
    ).fetchall()
    counts["orphan_vendors_removed"] = len(orphan_vendors)
    for (vendor_id,) in orphan_vendors:
        conn.execute(
            "DELETE FROM vendors WHERE company_id = ? AND vendor_id = ?",
            (company_id, vendor_id),
        )
    conn.commit()
    return counts


def find_harrington_runs() -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT document_id, filename, stage2_status
        FROM invoice_runs
        WHERE extraction_json LIKE '%Harrington%'
        ORDER BY upload_timestamp DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def rerun_document(document_id: str) -> dict:
    run = repository.get_run(document_id)
    if not run:
        raise ValueError(f"Invoice run not found: {document_id}")

    extraction = InvoiceExtraction.model_validate(run["extraction_json"])
    verification_data = run.get("verification_json")
    verification = (
        VerificationResult.model_validate(verification_data)
        if isinstance(verification_data, dict)
        else VerificationResult(verification_status="unavailable", overall_confidence=0)
    )
    reconciliation_data = run.get("reconciliation_json")
    reconciliation = (
        ReconciliationResult.model_validate(reconciliation_data)
        if isinstance(reconciliation_data, dict)
        else None
    )

    result = rerun_stages_2_through_5(
        document_id,
        extraction,
        verification=verification,
        reconciliation=reconciliation,
    )
    return {
        "document_id": document_id,
        "filename": run.get("filename"),
        "status": result.status,
        "stage2_status": result.stage2_status,
        "stage3_status": result.stage3_status,
        "stage4_decision": result.stage4_decision,
        "matched_pos": [
            p.po_number for p in (result.match_package.matched_pos or [])
        ]
        if result.match_package
        else [],
        "candidate_count": result.match_package.candidate_count
        if result.match_package
        else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", action="append", dest="document_ids")
    parser.add_argument("--company-id", default="DEFAULT")
    args = parser.parse_args()

    init_db()
    removed = clear_demo_master(args.company_id)
    print("Removed demo master data:", json.dumps(removed, indent=2))

    src_count = get_connection().execute(
        "SELECT COUNT(*) FROM source_records WHERE company_id = ?",
        (args.company_id,),
    ).fetchone()[0]
    print(f"Kept {src_count} source_records from your imports")

    po_count = get_connection().execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE company_id = ?",
        (args.company_id,),
    ).fetchone()[0]
    print(f"POs remaining: {po_count}")

    if args.document_ids:
        targets = [{"document_id": did} for did in args.document_ids]
    else:
        targets = find_harrington_runs()

    if not targets:
        print("No Harrington invoice runs found to re-run.")
        return

    print(f"Re-running {len(targets)} invoice(s)...")
    for row in targets:
        doc_id = row["document_id"]
        try:
            out = rerun_document(doc_id)
            print(json.dumps(out, indent=2))
        except Exception as exc:
            print(f"Failed {doc_id}: {exc}", file=sys.stderr)

    close_db()


if __name__ == "__main__":
    main()
