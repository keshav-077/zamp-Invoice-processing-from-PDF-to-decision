"""
Full demo environment reset: invoice processing history + upload master (+ optional seed POs).

Usage (from invoiceflow-ai/):
  python scripts/reset_demo_environment.py
  python scripts/reset_demo_environment.py --keep-seed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import close_db, get_connection, init_db  # noqa: E402
from scripts.clear_upload_master_data import clear_upload_master  # noqa: E402


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _delete_all(conn, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.execute(f"DELETE FROM {table}")
    return count


def clear_invoice_history(conn) -> dict[str, int]:
    """Remove all invoice pipeline runs and dependent audit rows."""
    counts: dict[str, int] = {}
    # Child / audit tables first (FK order)
    for table in (
        "explanation_snapshots",
        "audit_ledger",
        "po_confirmations",
        "review_work_items",
        "decision_records",
        "validation_runs",
        "po_match_results",
        "invoice_allocations",
        "processing_jobs",
        "extraction_feedback",
    ):
        counts[table] = _delete_all(conn, table)
    counts["invoice_runs"] = _delete_all(conn, "invoice_runs")
    return counts


def clear_all_po_master(conn, company_id: str = "DEFAULT") -> dict[str, int]:
    """Remove every PO master row (seed + import) for a clean CSV-only demo."""
    counts: dict[str, int] = {}
    po_numbers = [
        r[0]
        for r in conn.execute(
            "SELECT po_number FROM purchase_orders WHERE company_id = ?",
            (company_id,),
        ).fetchall()
    ]
    counts["purchase_orders"] = len(po_numbers)
    for po_number in po_numbers:
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
    counts["vendors"] = conn.execute(
        "SELECT COUNT(*) FROM vendors WHERE company_id = ?",
        (company_id,),
    ).fetchone()[0]
    conn.execute("DELETE FROM vendors WHERE company_id = ?", (company_id,))
    return counts


def reset_demo_environment(
    company_id: str = "DEFAULT",
    keep_seed: bool = False,
) -> dict:
    init_db()
    conn = get_connection()

    invoice_counts = clear_invoice_history(conn)
    conn.commit()

    upload_result = clear_upload_master(company_id)

    po_wipe: dict[str, int] = {}
    if not keep_seed:
        po_wipe = clear_all_po_master(conn, company_id)
        conn.commit()

    remaining = {
        "invoice_runs": conn.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0],
        "source_records": conn.execute(
            "SELECT COUNT(*) FROM source_records WHERE company_id = ?",
            (company_id,),
        ).fetchone()[0],
        "purchase_orders": conn.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE company_id = ?",
            (company_id,),
        ).fetchone()[0],
        "vendors": conn.execute(
            "SELECT COUNT(*) FROM vendors WHERE company_id = ?",
            (company_id,),
        ).fetchone()[0],
    }

    return {
        "invoice_history_removed": invoice_counts,
        "upload_master_removed": upload_result.get("removed", {}),
        "po_master_wiped": po_wipe,
        "remaining": remaining,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Full demo environment reset")
    parser.add_argument("--company-id", default="DEFAULT")
    parser.add_argument(
        "--keep-seed",
        action="store_true",
        help="Preserve non-import developer seed POs after upload master clear",
    )
    args = parser.parse_args()

    result = reset_demo_environment(args.company_id, keep_seed=args.keep_seed)
    print(json.dumps(result, indent=2))
    close_db()


if __name__ == "__main__":
    main()
