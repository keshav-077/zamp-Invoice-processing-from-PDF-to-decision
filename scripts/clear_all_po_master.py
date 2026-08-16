"""Remove all PO master data from the database (seed + import-mirrored)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import close_db, get_connection, init_db  # noqa: E402


def clear_all_po_master(company_id: str | None = None) -> dict:
    conn = get_connection()
    scope = f" WHERE company_id = '{company_id}'" if company_id else ""
    tables = [
        "invoice_allocations",
        "po_lines",
        "grn_records",
        "po_references",
        "purchase_orders",
    ]
    counts: dict[str, int] = {}
    for table in tables:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}{scope}").fetchone()[0]

    for table in tables:
        conn.execute(f"DELETE FROM {table}{scope}")

    vendor_scope = f" WHERE company_id = '{company_id}'" if company_id else ""
    counts["vendors"] = conn.execute(f"SELECT COUNT(*) FROM vendors{vendor_scope}").fetchone()[0]
    conn.execute(f"DELETE FROM vendors{vendor_scope}")

    sr_scope = f" AND company_id = '{company_id}'" if company_id else ""
    counts["source_records_po_refs_cleared"] = conn.execute(
        f"SELECT COUNT(*) FROM source_records WHERE po_reference IS NOT NULL{sr_scope}"
    ).fetchone()[0]
    conn.execute(
        f"UPDATE source_records SET po_reference = NULL, po_reference_status = NULL "
        f"WHERE po_reference IS NOT NULL{sr_scope}"
    )

    conn.commit()

    remaining = {table: conn.execute(f"SELECT COUNT(*) FROM {table}{scope}").fetchone()[0] for table in tables}
    remaining["vendors"] = conn.execute(f"SELECT COUNT(*) FROM vendors{vendor_scope}").fetchone()[0]
    remaining["source_records"] = conn.execute(
        f"SELECT COUNT(*) FROM source_records{' WHERE company_id = ?' if company_id else ''}",
        (company_id,) if company_id else (),
    ).fetchone()[0]

    return {"removed": counts, "remaining": remaining}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Clear all PO master database entries")
    parser.add_argument("--company-id", default=None, help="Limit to one company (default: all)")
    args = parser.parse_args()

    init_db()
    result = clear_all_po_master(args.company_id)
    print(json.dumps(result, indent=2))
    close_db()


if __name__ == "__main__":
    main()
