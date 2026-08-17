"""Dialect-safe SQL helpers for SQLite and Postgres."""

from __future__ import annotations


def is_postgres() -> bool:
    from app.db import database

    return database._is_postgres


def now_expr() -> str:
    return "NOW()" if is_postgres() else "datetime('now')"


def build_upsert_sql(
    table: str,
    columns: list[str],
    conflict_columns: list[str],
    placeholder: str = "?",
) -> str:
    """
    SQLite: INSERT OR REPLACE (full row replace on PK conflict).
    Postgres: INSERT ... ON CONFLICT DO UPDATE SET ...
    """
    col_list = ", ".join(columns)
    placeholders = ", ".join([placeholder] * len(columns))
    if not is_postgres():
        return f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"

    conflict = ", ".join(conflict_columns)
    update_cols = [c for c in columns if c not in conflict_columns]
    if not update_cols:
        return (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO NOTHING"
        )
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    return (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {sets}"
    )
