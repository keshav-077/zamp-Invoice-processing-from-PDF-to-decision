"""Dialect-safe SQL helpers for SQLite and Postgres."""

from __future__ import annotations


def is_postgres() -> bool:
    from app.db import database

    return database._is_postgres


def now_expr() -> str:
    return "NOW()" if is_postgres() else "datetime('now')"
