"""
Build data/PO.xlsx from data/invoice_catalog.json.

Usage (from invoiceflow-ai/):
  python scripts/build_po_xlsx.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "invoice_catalog.json"
OUTPUT = ROOT / "data" / "PO.xlsx"


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def short_alias(name: str) -> str:
    parts = re.split(r"[,.\s]+", name)
    return " ".join(p for p in parts if p)[:40]


def build():
    try:
        import pandas as pd
    except ImportError:
        print("Install pandas and openpyxl: pip install pandas openpyxl")
        sys.exit(1)

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    invoices = catalog["invoices"]

    # --- Vendors ---
    vendor_map: dict[str, dict] = {}
    for inv in invoices:
        name = inv.get("vendor_name")
        if not name:
            continue
        key = normalize_name(name)
        if key not in vendor_map:
            vid = f"V{len(vendor_map) + 1:03d}"
            vendor_map[key] = {
                "vendor_id": vid,
                "name": name,
                "normalized_name": normalize_name(name),
                "aliases": json.dumps([short_alias(name)]),
                "tax_id": "",
                "supplier_code": "",
                "status": "active",
            }

    # --- Purchase orders ---
    po_rows = []
    po_lines = []
    grn_rows = []

    def vendor_id_for(name: str) -> str:
        return vendor_map[normalize_name(name)]["vendor_id"]

    def add_po(
        po_number: str,
        vendor_name: str,
        total: float,
        po_type: str = "blanket",
        status: str = "open",
        previously_invoiced: float = 0.0,
        issue_date: str = "2016-01-01",
        lines: list | None = None,
        grn_amount: float | None = None,
    ):
        po_rows.append(
            {
                "po_number": po_number,
                "vendor_id": vendor_id_for(vendor_name),
                "vendor_name": vendor_name,
                "total_amount": total,
                "currency": "USD",
                "status": status,
                "po_type": po_type,
                "issue_date": issue_date,
                "expiry_date": "2027-12-31",
                "received_amount": grn_amount or 0.0,
                "previously_invoiced": previously_invoiced,
            }
        )
        if lines:
            for i, line in enumerate(lines, start=1):
                po_lines.append(
                    {
                        "po_number": po_number,
                        "line_number": i,
                        "description": line["description"],
                        "sku": line.get("sku", f"SKU-{i:03d}"),
                        "quantity": line.get("quantity", 1),
                        "unit_price": line.get("unit_price", line.get("amount", 0)),
                        "amount": line.get("amount", 0),
                        "uom": "each",
                    }
                )
        if po_type == "standard" and grn_amount:
            grn_rows.append(
                {
                    "grn_id": f"GRN-{po_number}",
                    "po_number": po_number,
                    "received_date": issue_date,
                    "received_amount": grn_amount,
                    "status": "confirmed",
                }
            )

    # Build POs from catalog assignments
    for inv in invoices:
        po_num = inv.get("assigned_po_number")
        if not po_num:
            continue
        vendor = inv["vendor_name"]
        total = float(inv.get("total_amount") or 0)
        po_total = max(total * 3, total + 5000, 10000)
        lines = inv.get("line_items") or [
            {"description": "Professional services per agreement", "quantity": 1, "amount": total}
        ]
        # Split PO: d13 second invoice
        prev_inv = 120.0 if inv.get("demo_role") == "edge_split_po_second_invoice" else 0.0
        add_po(
            po_number=po_num,
            vendor_name=vendor,
            total=po_total,
            po_type="blanket",
            previously_invoiced=prev_inv,
            issue_date=inv.get("invoice_date") or "2016-01-01",
            lines=lines,
        )

    # d2 uses PO number from invoice (34313) not PO-34313
    add_po(
        po_number="PO-34313",
        vendor_name="Microbiological Associates",
        total=50000.0,
        po_type="blanket",
        issue_date="1986-06-01",
        lines=[
            {"description": "Hepatic enzyme induction study B70", "quantity": 1, "unit_price": 2500, "amount": 2500},
            {"description": "Hepatic enzyme induction study B66", "quantity": 1, "unit_price": 2500, "amount": 2500},
        ],
    )
    # Also register raw PO 34313 as alias match target
    add_po(
        po_number="34313",
        vendor_name="Microbiological Associates",
        total=50000.0,
        po_type="blanket",
        issue_date="1986-06-01",
        lines=[
            {"description": "Hepatic enzyme induction study B70", "quantity": 1, "unit_price": 2500, "amount": 2500},
            {"description": "Hepatic enzyme induction study B66", "quantity": 1, "unit_price": 2500, "amount": 2500},
        ],
    )

    # Ambiguous PO pair for d8 (Oconnor Fuller Carter)
    add_po(
        po_number="PO-8801",
        vendor_name="Oconnor, Fuller and Carter",
        total=5000.0,
        po_type="blanket",
        issue_date="1995-01-01",
        lines=[{"description": "Retail merchandise assortment A", "quantity": 1, "amount": 68.0}],
    )
    add_po(
        po_number="PO-8802",
        vendor_name="Oconnor, Fuller and Carter",
        total=4800.0,
        po_type="blanket",
        issue_date="1995-01-01",
        lines=[{"description": "Retail merchandise assortment B", "quantity": 1, "amount": 70.0}],
    )

    # RTI PO with handwritten correction
    add_po(
        po_number="PO-346A",
        vendor_name="Research Triangle Institute",
        total=10000.0,
        po_type="blanket",
        issue_date="1987-01-01",
        lines=[{"description": "Metabolite identification contract labor", "quantity": 1, "amount": 60.78}],
    )
    add_po(
        po_number="346A",
        vendor_name="Research Triangle Institute",
        total=10000.0,
        po_type="blanket",
        issue_date="1987-01-01",
        lines=[{"description": "Metabolite identification contract labor", "quantity": 1, "amount": 60.78}],
    )

    # Closed PO edge (historical)
    add_po(
        po_number="PO-CLOSED-01",
        vendor_name="Branham, INC.",
        total=5000.0,
        po_type="blanket",
        status="closed",
        issue_date="1988-01-01",
        lines=[{"description": "Closed PO reference ad buy", "quantity": 1, "amount": 1345.76}],
    )

    # Split billing demo — one PO consumed by two invoices
    split_vendor = "Split Billing Demo Corp"
    if normalize_name(split_vendor) not in vendor_map:
        vid = f"V{len(vendor_map) + 1:03d}"
        vendor_map[normalize_name(split_vendor)] = {
            "vendor_id": vid,
            "name": split_vendor,
            "normalized_name": normalize_name(split_vendor),
            "aliases": json.dumps(["Split Billing Demo"]),
            "tax_id": "",
            "supplier_code": "",
            "status": "active",
        }
    add_po(
        po_number="PO-SPLIT-01",
        vendor_name="Split Billing Demo Corp",
        total=10000.0,
        po_type="blanket",
        previously_invoiced=4000.0,
        issue_date="2024-01-01",
        lines=[
            {"description": "Professional services — phase A", "quantity": 1, "amount": 4000.0},
            {"description": "Professional services — phase B", "quantity": 1, "amount": 3500.0},
        ],
    )

    # Standard goods PO with GRN for optional 3-way demo
    add_po(
        po_number="PO-GOODS-01",
        vendor_name="Gates, Myers and Stone",
        total=2000.0,
        po_type="standard",
        issue_date="2016-06-01",
        lines=[{"description": "Gift set wholesale order", "quantity": 1, "amount": 161.99}],
        grn_amount=161.99,
    )

    vendors_df = pd.DataFrame(list(vendor_map.values()))

    # Rich aliases for Rogers demo vendor (crumpled scan matching)
    rogers_key = normalize_name("Rogers, Smith and Hobbs")
    if rogers_key in vendor_map:
        vendor_map[rogers_key]["aliases"] = json.dumps([
            "Rogers Smith and Hobbs",
            "Rogers, Smith & Hobbs",
            "Rogers Smith Hobbs",
            "Rogers Smith and Hobbs IT",
        ])
        vendors_df = pd.DataFrame(list(vendor_map.values()))

    po_df = pd.DataFrame(po_rows).drop_duplicates(subset=["po_number"])
    lines_df = pd.DataFrame(po_lines).drop_duplicates(subset=["po_number", "line_number"])
    grn_df = pd.DataFrame(grn_rows).drop_duplicates(subset=["grn_id"]) if grn_rows else pd.DataFrame(
        columns=["grn_id", "po_number", "received_date", "received_amount", "status"]
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUTPUT, engine="openpyxl") as writer:
        vendors_df.to_excel(writer, sheet_name="Vendors", index=False)
        po_df.to_excel(writer, sheet_name="PurchaseOrders", index=False)
        lines_df.to_excel(writer, sheet_name="POLines", index=False)
        grn_df.to_excel(writer, sheet_name="GRN", index=False)

    print(f"Wrote {OUTPUT}")
    print(f"  Vendors: {len(vendors_df)}")
    print(f"  POs: {len(po_df)}")
    print(f"  PO lines: {len(lines_df)}")
    print(f"  GRN: {len(grn_df)}")


if __name__ == "__main__":
    build()
