"""
Reset database and re-seed from data/PO.xlsx.

Usage (from invoiceflow-ai/):
  python scripts/reset_db.py

Uses DATABASE_URL (Postgres/Neon) when set, otherwise local SQLite.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db.database import close_db, init_db, get_connection, _is_postgres, scalar_row  # noqa: E402
from app.db import repository  # noqa: E402
from app.db.seed_data import seed_database  # noqa: E402

# Child tables first (Postgres DELETE order) — full wipe including invoice history
_TRUNCATE_TABLES = [
    "processing_jobs",
    "extraction_feedback",
    "po_confirmations",
    "human_actions",
    "audit_ledger",
    "explanation_snapshots",
    "decision_records",
    "validation_runs",
    "po_match_results",
    "invoice_allocations",
    "invoice_runs",
    "review_work_items",
    *repository.MASTER_DATA_TABLES,
    "companies",
]


def _clear_postgres_data(conn) -> None:
    for table in _TRUNCATE_TABLES:
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            if hasattr(conn, "rollback"):
                conn.rollback()
    conn.commit()


def reset(clear_only: bool = False) -> None:
    close_db()

    if settings.database_url:
        import app.db.database as db_mod

        db_mod._connection = None
        init_db()
        conn = get_connection()
        if _is_postgres:
            if clear_only:
                repository.clear_master_data()
                print(f"Cleared master data only ({settings.database_url[:40]}...)")
            else:
                _clear_postgres_data(conn)
                print(f"Cleared Postgres tables ({settings.database_url[:40]}...)")
            if not clear_only:
                seed_database()
    else:
        db_path = settings.db_path
        if clear_only:
            import app.db.database as db_mod

            db_mod._connection = None
            init_db()
            repository.clear_master_data()
            print("Cleared master data only (SQLite)")
        else:
            if db_path.exists():
                db_path.unlink()
                for suffix in ("-wal", "-shm"):
                    extra = Path(str(db_path) + suffix)
                    if extra.exists():
                        extra.unlink()
                print(f"Deleted {db_path}")
            import app.db.database as db_mod

            db_mod._connection = None
            init_db()
            seed_database()

    conn = get_connection()
    vendors = scalar_row(conn.execute("SELECT COUNT(*) FROM vendors").fetchone())
    pos = scalar_row(conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone())
    src = scalar_row(conn.execute("SELECT COUNT(*) FROM source_records").fetchone())
    backend = "Postgres" if settings.database_url else "SQLite"
    if clear_only:
        print(f"Master data cleared ({backend}): {vendors} vendors, {pos} POs, {src} source records")
    else:
        print(f"Re-seeded ({backend}): {vendors} vendors, {pos} POs, {src} source records")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Remove master/import data only; do not re-seed demo PO.xlsx",
    )
    args = parser.parse_args()
    reset(clear_only=args.clear_only)
