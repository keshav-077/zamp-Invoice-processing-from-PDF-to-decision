"""Tests for dialect-safe SQL helpers."""

from app.db import sql_dialect


def test_build_upsert_sql_sqlite(monkeypatch):
    monkeypatch.setattr(sql_dialect, "is_postgres", lambda: False)
    sql = sql_dialect.build_upsert_sql(
        "invoice_runs",
        ["document_id", "filename"],
        ["document_id"],
    )
    assert "INSERT OR REPLACE INTO invoice_runs" in sql
    assert "ON CONFLICT" not in sql


def test_build_upsert_sql_postgres(monkeypatch):
    monkeypatch.setattr(sql_dialect, "is_postgres", lambda: True)
    sql = sql_dialect.build_upsert_sql(
        "invoice_runs",
        ["document_id", "filename"],
        ["document_id"],
    )
    assert "INSERT INTO invoice_runs" in sql
    assert "ON CONFLICT (document_id) DO UPDATE SET filename = EXCLUDED.filename" in sql
