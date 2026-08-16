"""
Mirror existing source_records into purchase_orders (one-time / idempotent sync).

Usage (from invoiceflow-ai/):
  python scripts/sync_source_records_to_po_master.py
  python scripts/sync_source_records_to_po_master.py --company-id DEFAULT
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import close_db, get_connection, init_db  # noqa: E402
from app.db import repository  # noqa: E402
from app.services.import_po_mirror import build_mirrored_po_row, ensure_vendor_for_mirror  # noqa: E402
from app.services.adaptive_importer import _ensure_vendor_row  # noqa: E402
from app.services.vendor_identity import vendor_names_equivalent  # noqa: E402


def sync_company(company_id: str = "DEFAULT", repair: bool = False) -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM source_records WHERE company_id = ? ORDER BY created_at",
        (company_id,),
    ).fetchall()

    vendor_by_id = {v["vendor_id"]: v for v in repository.get_all_vendors(company_id)}
    vendor_by_supplier: dict = {}
    vendor_by_tax: dict = {}
    vendor_by_norm: dict = {}
    for v in vendor_by_id.values():
        if v.get("supplier_code"):
            vendor_by_supplier[v["supplier_code"]] = v
        if v.get("tax_id"):
            vendor_by_tax[v["tax_id"]] = v
        vendor_by_norm[v.get("normalized_name") or ""] = v

    vendor_rows: list[dict] = []
    po_rows: list[dict] = []
    po_numbers_seen = {p["po_number"] for p in repository.get_all_open_pos(company_id)}
    po_numbers_seen.update(
        r[0]
        for r in conn.execute(
            "SELECT po_number FROM purchase_orders WHERE company_id = ?",
            (company_id,),
        ).fetchall()
    )

    mirrored = 0
    skipped = 0
    repaired = 0
    for row in rows:
        d = dict(row)
        meta = {}
        if d.get("metadata_json"):
            try:
                meta = json.loads(d["metadata_json"])
            except json.JSONDecodeError:
                meta = {}

        source_record_id = d["source_record_id"]
        existing_po = conn.execute(
            """
            SELECT po_number, vendor_id, vendor_name FROM purchase_orders
            WHERE company_id = ? AND metadata_json LIKE ?
            """,
            (company_id, f'%"source_record_id": "{source_record_id}"%'),
        ).fetchone()
        if existing_po and not repair:
            skipped += 1
            continue

        invoice_total = float(d.get("invoice_total") or 0)
        if invoice_total <= 0:
            skipped += 1
            continue

        vendor_name = d.get("vendor_name") or ""
        mirror_vendor_id = ensure_vendor_for_mirror(
            company_id,
            d.get("vendor_id"),
            vendor_name,
            vendor_by_id,
            vendor_by_supplier,
            vendor_by_tax,
            vendor_by_norm,
            vendor_rows,
            meta,
            _ensure_vendor_row,
        )
        if not mirror_vendor_id:
            skipped += 1
            continue

        if existing_po and repair:
            po_vendor_name = existing_po["vendor_name"] or ""
            vendor_row = vendor_by_id.get(existing_po["vendor_id"] or "")
            vendor_ok = vendor_row and vendor_names_equivalent(
                vendor_row.get("name"), vendor_name
            )
            if (
                existing_po["vendor_id"] == mirror_vendor_id
                and vendor_names_equivalent(po_vendor_name, vendor_name)
                and vendor_ok
            ):
                skipped += 1
                continue

        po_row = build_mirrored_po_row(
            source_record_id=source_record_id,
            company_id=company_id,
            vendor_id=mirror_vendor_id,
            vendor_name=vendor_name,
            invoice_total=invoice_total,
            currency=d.get("currency") or "USD",
            po_reference=d.get("po_reference"),
            import_batch_id=d.get("import_batch_id"),
            invoice_number=d.get("invoice_number"),
            invoice_date=d.get("invoice_date"),
            po_numbers_seen=po_numbers_seen,
        )
        if not po_row:
            skipped += 1
            continue

        if existing_po and repair:
            po_row["po_number"] = existing_po["po_number"]
            po_numbers_seen.add(po_row["po_number"])
            po_rows.append(po_row)
            repaired += 1
            continue

        po_numbers_seen.add(po_row["po_number"])
        po_rows.append(po_row)
        mirrored += 1

        if not d.get("po_reference"):
            conn.execute(
                """
                UPDATE source_records SET po_reference = ?, po_reference_status = ?
                WHERE source_record_id = ?
                """,
                (po_row["po_number"], "mirrored", source_record_id),
            )

    if vendor_rows:
        repository.upsert_vendors(vendor_rows)
        for v in vendor_rows:
            vendor_by_id[v["vendor_id"]] = v
    if po_rows:
        repository.upsert_purchase_orders(po_rows)

    return {
        "mirrored": mirrored,
        "repaired": repaired,
        "skipped": skipped,
        "total_source_records": len(rows),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", default="DEFAULT")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Re-upsert mirrored POs when vendor_id/name drift from source_records",
    )
    args = parser.parse_args()

    init_db()
    result = sync_company(args.company_id, repair=args.repair)
    print(json.dumps(result, indent=2))
    close_db()


if __name__ == "__main__":
    main()
