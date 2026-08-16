"""
Upsert Rogers demo vendor + PO into the live database (no DB file delete).

Use when uvicorn is running and reset_db.py fails with PermissionError.

Usage:
  python scripts/seed_rogers_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import get_connection  # noqa: E402

VENDOR_ID = "V019"
VENDOR_NAME = "Rogers, Smith and Hobbs"
PO_NUMBER = "PO-ROGERS-01"

ROGERS_LINES = [
    ("Giant 50'S Christmas Cracker", 1, 2.89, 2.89),
    ("Set 12 Colour Pencils Spaceboy", 7, 0.65, 4.55),
    ("Heart Ivory Trellis Large", 4, 1.65, 6.60),
    ("Baking Mould Heart White Chocolate", 10, 2.55, 25.50),
    ("Grow Your Own Flowers Set Of 3", 9, 7.95, 71.55),
    ("Edwardian Parasol Black", 10, 12.46, 124.60),
    ("Plasters In Tin Vintage Paisley", 8, 1.65, 13.20),
]

ALIASES = json.dumps([
    "Rogers Smith and Hobbs",
    "Rogers, Smith & Hobbs",
    "Rogers Smith Hobbs",
    "Rogers Smith and Hobbs IT",
])


def upsert() -> None:
    conn = get_connection()

    existing = conn.execute(
        "SELECT vendor_id FROM vendors WHERE vendor_id = ? OR normalized_name = ?",
        (VENDOR_ID, "rogers, smith and hobbs"),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE vendors SET
                name = ?, normalized_name = ?, aliases_json = ?, status = 'active'
            WHERE vendor_id = ?
            """,
            (VENDOR_NAME, "rogers, smith and hobbs", ALIASES, dict(existing)["vendor_id"]),
        )
        vendor_id = dict(existing)["vendor_id"]
        print(f"Updated vendor {vendor_id}")
    else:
        conn.execute(
            """
            INSERT INTO vendors (vendor_id, name, normalized_name, aliases_json, tax_id, supplier_code, status)
            VALUES (?, ?, ?, ?, '', '', 'active')
            """,
            (VENDOR_ID, VENDOR_NAME, "rogers, smith and hobbs", ALIASES),
        )
        vendor_id = VENDOR_ID
        print(f"Inserted vendor {vendor_id}")

    po_row = conn.execute(
        "SELECT po_number FROM purchase_orders WHERE po_number = ?",
        (PO_NUMBER,),
    ).fetchone()

    if po_row:
        conn.execute(
            """
            UPDATE purchase_orders SET
                vendor_id = ?, vendor_name = ?, total_amount = 10000.0,
                currency = 'USD', status = 'open', po_type = 'blanket',
                issue_date = '1987-01-01', expiry_date = '2027-12-31',
                previously_invoiced = 0.0
            WHERE po_number = ?
            """,
            (vendor_id, VENDOR_NAME, PO_NUMBER),
        )
        print(f"Updated PO {PO_NUMBER}")
    else:
        conn.execute(
            """
            INSERT INTO purchase_orders
            (po_number, vendor_id, vendor_name, total_amount, currency, status, po_type,
             issue_date, expiry_date, received_amount, previously_invoiced)
            VALUES (?, ?, ?, 10000.0, 'USD', 'open', 'blanket', '1987-01-01', '2027-12-31', 0.0, 0.0)
            """,
            (PO_NUMBER, vendor_id, VENDOR_NAME),
        )
        print(f"Inserted PO {PO_NUMBER}")

    conn.execute("DELETE FROM po_lines WHERE po_number = ?", (PO_NUMBER,))
    for i, (desc, qty, unit, amt) in enumerate(ROGERS_LINES, start=1):
        conn.execute(
            """
            INSERT INTO po_lines (po_number, line_number, description, sku, quantity, unit_price, amount, uom)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'each')
            """,
            (PO_NUMBER, i, desc, f"SKU-R{i:03d}", qty, unit, amt),
        )
    print(f"Inserted {len(ROGERS_LINES)} PO lines")

    conn.commit()
    po = conn.execute(
        "SELECT total_amount, previously_invoiced FROM purchase_orders WHERE po_number = ?",
        (PO_NUMBER,),
    ).fetchone()
    d = dict(po)
    remaining = d["total_amount"] - d["previously_invoiced"]
    print(f"Done. PO {PO_NUMBER} remaining balance: ${remaining:,.2f} (invoice total $300.46)")


if __name__ == "__main__":
    upsert()
