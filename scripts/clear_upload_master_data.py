"""
Remove all master data created via Upload Master (adaptive / legacy import).

Clears:
  - source_records, master_data_imports, import_staging_*, mapping_profiles
  - purchase_orders mirrored from uploads (import_derived / IMP-* / import_batch_id)
  - child po_lines, grn_records, po_references, invoice_allocations for those POs
  - vendors with no remaining PO references (orphans after upload PO removal)

Preserves developer seed POs (no import_derived / no IMP-* prefix).

Usage (from invoiceflow-ai/):
  python scripts/clear_upload_master_data.py
  python scripts/clear_upload_master_data.py --company-id DEFAULT
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import close_db, get_connection, init_db  # noqa: E402


def _upload_po_numbers(conn, company_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT po_number FROM purchase_orders
        WHERE company_id = ?
          AND (
            po_number LIKE 'IMP-%'
            OR metadata_json LIKE '%"import_derived": true%'
            OR metadata_json LIKE '%"import_batch_id":%'
          )
        """,
        (company_id,),
    ).fetchall()
    return [r[0] for r in rows]


def clear_upload_master(company_id: str = "DEFAULT") -> dict:
    conn = get_connection()

    counts_before = {
        "source_records": conn.execute(
            "SELECT COUNT(*) FROM source_records WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "master_data_imports": conn.execute(
            "SELECT COUNT(*) FROM master_data_imports WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "import_staging_batches": conn.execute(
            "SELECT COUNT(*) FROM import_staging_batches WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "import_staging_rows": conn.execute(
            """
            SELECT COUNT(*) FROM import_staging_rows
            WHERE batch_id IN (
                SELECT batch_id FROM import_staging_batches WHERE company_id = ?
            )
            """,
            (company_id,),
        ).fetchone()[0],
        "mapping_profiles": conn.execute(
            "SELECT COUNT(*) FROM mapping_profiles WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "upload_pos": len(_upload_po_numbers(conn, company_id)),
    }

    upload_pos = _upload_po_numbers(conn, company_id)
    for po_number in upload_pos:
        conn.execute(
            "DELETE FROM invoice_allocations WHERE company_id = ? AND po_number = ?",
            (company_id, po_number),
        )
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

    conn.execute("DELETE FROM source_records WHERE company_id = ?", (company_id,))

    batch_ids = [
        r[0]
        for r in conn.execute(
            "SELECT batch_id FROM import_staging_batches WHERE company_id = ?",
            (company_id,),
        ).fetchall()
    ]
    for batch_id in batch_ids:
        conn.execute("DELETE FROM import_staging_rows WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM import_staging_batches WHERE company_id = ?", (company_id,))

    conn.execute("DELETE FROM master_data_imports WHERE company_id = ?", (company_id,))
    conn.execute("DELETE FROM mapping_profiles WHERE company_id = ?", (company_id,))

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
    counts_before["orphan_vendors_removed"] = len(orphan_vendors)
    for (vendor_id,) in orphan_vendors:
        conn.execute(
            "DELETE FROM vendors WHERE company_id = ? AND vendor_id = ?",
            (company_id, vendor_id),
        )

    conn.commit()

    remaining = {
        "source_records": conn.execute(
            "SELECT COUNT(*) FROM source_records WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "master_data_imports": conn.execute(
            "SELECT COUNT(*) FROM master_data_imports WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "import_staging_batches": conn.execute(
            "SELECT COUNT(*) FROM import_staging_batches WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "mapping_profiles": conn.execute(
            "SELECT COUNT(*) FROM mapping_profiles WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "upload_pos": len(_upload_po_numbers(conn, company_id)),
        "purchase_orders_total": conn.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
        "vendors_total": conn.execute(
            "SELECT COUNT(*) FROM vendors WHERE company_id = ?", (company_id,)
        ).fetchone()[0],
    }

    return {"removed": counts_before, "remaining": remaining}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Clear Upload Master data from the database")
    parser.add_argument("--company-id", default="DEFAULT")
    args = parser.parse_args()

    init_db()
    result = clear_upload_master(args.company_id)
    print(json.dumps(result, indent=2))
    close_db()


if __name__ == "__main__":
    main()
