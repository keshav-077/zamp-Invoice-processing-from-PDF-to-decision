"""Apply schema migrations to DATABASE_URL (Neon)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import close_db, get_connection, init_db  # noqa: E402


def main() -> None:
    close_db()
    init_db()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'import_staging_rows'
        ORDER BY column_name
        """
    ).fetchall()
    cols = [r["column_name"] for r in rows]
    print("import_staging_rows columns:", cols)
    if "classification_json" not in cols:
        raise SystemExit("classification_json still missing")
    print("OK")


if __name__ == "__main__":
    main()
