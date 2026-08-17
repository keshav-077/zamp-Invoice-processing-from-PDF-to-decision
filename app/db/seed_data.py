"""
InvoiceFlow AI — Seed Data

Populates Vendor Master, Purchase Orders, PO Lines, and GRN records
with realistic data that matches our test invoice scenarios.
"""

import json
import logging
from pathlib import Path
import pandas as pd
from app.db.database import get_connection

logger = logging.getLogger(__name__)

def _load_excel(path: Path) -> dict:
    """Load all required sheets from the Excel file and return a dict."""
    return {
        "vendors": pd.read_excel(path, sheet_name="Vendors"),
        "purchase_orders": pd.read_excel(path, sheet_name="PurchaseOrders"),
        "po_lines": pd.read_excel(path, sheet_name="POLines"),
        "grn": pd.read_excel(path, sheet_name="GRN"),
    }

def seed_database() -> None:
    """Insert seed data into the database if not already present."""
    conn = get_connection()

    # Idempotency check – if vendors already exist, assume data is seeded
    from app.db.database import scalar_row

    if scalar_row(conn.execute("SELECT COUNT(*) FROM vendors").fetchone()) > 0:
        logger.info("Database already seeded — skipping")
        return

    logger.info("Seeding database from PO.xlsx...")
    excel_path = Path(__file__).resolve().parents[2] / "data" / "PO.xlsx"
    if not excel_path.exists():
        logger.error(
            "PO master file not found at %s — run: python scripts/build_po_xlsx.py",
            excel_path,
        )
        return
    sheets = _load_excel(excel_path)

    # Vendors
    df_v = sheets["vendors"]

    def _aliases_json(val) -> str:
        if isinstance(val, (list, tuple)):
            return json.dumps(list(val))
        if isinstance(val, str):
            stripped = val.strip()
            if stripped.startswith("["):
                return stripped
            if stripped:
                return json.dumps([stripped])
        return json.dumps([])

    if "aliases" in df_v.columns:
        df_v["aliases_json"] = df_v["aliases"].apply(_aliases_json)
    else:
        df_v["aliases_json"] = json.dumps([])
    vendors = list(
        df_v[[
            "vendor_id",
            "name",
            "normalized_name",
            "aliases_json",
            "tax_id",
            "supplier_code",
            "status",
        ]].itertuples(index=False, name=None)
    )

    # Purchase Orders
    df_po = sheets["purchase_orders"]
    purchase_orders = list(
        df_po[[
            "po_number",
            "vendor_id",
            "vendor_name",
            "total_amount",
            "currency",
            "status",
            "po_type",
            "issue_date",
            "expiry_date",
            "received_amount",
            "previously_invoiced",
        ]].itertuples(index=False, name=None)
    )

    # PO Lines
    df_lines = sheets["po_lines"]
    po_lines = list(
        df_lines[[
            "po_number",
            "line_number",
            "description",
            "sku",
            "quantity",
            "unit_price",
            "amount",
            "uom",
        ]].itertuples(index=False, name=None)
    )

    # GRN records
    df_grn = sheets["grn"]
    grn_records = list(
        df_grn[[
            "grn_id",
            "po_number",
            "received_date",
            "received_amount",
            "status",
        ]].itertuples(index=False, name=None)
    )

    # Insert data into DB
    conn.executemany(
        "INSERT INTO vendors (vendor_id, name, normalized_name, aliases_json, tax_id, supplier_code, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        vendors,
    )
    conn.executemany(
        "INSERT INTO purchase_orders (po_number, vendor_id, vendor_name, total_amount, currency, status, po_type, issue_date, expiry_date, received_amount, previously_invoiced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        purchase_orders,
    )
    conn.executemany(
        "INSERT INTO po_lines (po_number, line_number, description, sku, quantity, unit_price, amount, uom) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        po_lines,
    )
    conn.executemany(
        "INSERT INTO grn_records (grn_id, po_number, received_date, received_amount, status) VALUES (?, ?, ?, ?, ?)",
        grn_records,
    )
    conn.commit()
    logger.info(
        f"Seeded: {len(vendors)} vendors, {len(purchase_orders)} POs, {len(po_lines)} PO lines, {len(grn_records)} GRN records"
    )
