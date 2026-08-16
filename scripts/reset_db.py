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
from app.db.database import close_db, init_db, get_connection, _is_postgres  # noqa: E402
from app.db.seed_data import seed_database  # noqa: E402

# Child tables first (Postgres DELETE order)
_TRUNCATE_TABLES = [
    "processing_jobs",
    "extraction_feedback",
    "po_confirmations",
    "human_actions",
    "audit_ledger",
    "explanation_snapshots",
    "validation_runs",
    "po_match_results",
    "invoice_allocations",
    "invoice_runs",
    "import_staging_rows",
    "source_records",
    "master_data_imports",
    "grn_records",
    "po_lines",
    "purchase_orders",
    "vendors",
    "companies",
]


def _clear_postgres_data(conn) -> None:
    for table in _TRUNCATE_TABLES:
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass
    conn.commit()


def reset() -> None:
    close_db()

    if settings.database_url:
        import app.db.database as db_mod

        db_mod._connection = None
        init_db()
        conn = get_connection()
        if _is_postgres:
            _clear_postgres_data(conn)
            print(f"Cleared Postgres tables ({settings.database_url[:40]}...)")
        seed_database()
    else:
        db_path = settings.db_path
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
    vendors = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
    pos = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
    src = conn.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]
    backend = "Postgres" if settings.database_url else "SQLite"
    print(f"Re-seeded ({backend}): {vendors} vendors, {pos} POs, {src} source records")


if __name__ == "__main__":
    reset()
