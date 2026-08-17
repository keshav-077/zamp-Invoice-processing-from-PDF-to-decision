"""
Clear PO master, vendors, imports, and source_records — does NOT re-seed demo data.

Usage (from invoiceflow-ai/):
  python scripts/clear_master_data.py
  python scripts/clear_master_data.py --company-id DEFAULT

Uses DATABASE_URL (Neon) when set in .env, otherwise local SQLite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db.database import close_db, get_connection, init_db, scalar_row  # noqa: E402
from app.db import repository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear master data (no demo re-seed)")
    parser.add_argument("--company-id", default=None, help="Scope delete to one company")
    args = parser.parse_args()

    close_db()
    import app.db.database as db_mod

    db_mod._connection = None
    init_db()

    backend = "Postgres" if settings.database_url else "SQLite"
    print(f"Clearing master data on {backend}...")
    result = repository.clear_master_data(company_id=args.company_id)
    conn = get_connection()
    vendors = scalar_row(conn.execute("SELECT COUNT(*) FROM vendors").fetchone())
    pos = scalar_row(conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone())
    src = scalar_row(conn.execute("SELECT COUNT(*) FROM source_records").fetchone())
    print(f"Done. Remaining: {vendors} vendors, {pos} POs, {src} source records")
    print("Re-upload your master data file in Master Data Import.")


if __name__ == "__main__":
    main()
