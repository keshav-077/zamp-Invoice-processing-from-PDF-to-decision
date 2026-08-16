"""
Reset SQLite database and re-seed from data/PO.xlsx.

Usage (from invoiceflow-ai/):
  python scripts/reset_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db.database import close_db, init_db, get_connection  # noqa: E402
from app.db.seed_data import seed_database  # noqa: E402


def reset() -> None:
    db_path = settings.db_path
    close_db()
    if db_path.exists():
        db_path.unlink()
        print(f"Deleted {db_path}")
    init_db()
    seed_database()
    conn = get_connection()
    vendors = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
    pos = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
    src = conn.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]
    print(f"Re-seeded: {vendors} vendors, {pos} POs, {src} source records")


if __name__ == "__main__":
    reset()
