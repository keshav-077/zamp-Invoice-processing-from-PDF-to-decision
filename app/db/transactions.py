"""Transaction context manager for atomic multi-table operations."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app.db.database import get_connection


@contextmanager
def db_transaction() -> Iterator[None]:
    conn = get_connection()
    try:
        yield
        conn.commit()
    except Exception:
        if hasattr(conn, "_conn"):
            conn._conn.rollback()
        elif hasattr(conn, "rollback"):
            conn.rollback()
        raise
