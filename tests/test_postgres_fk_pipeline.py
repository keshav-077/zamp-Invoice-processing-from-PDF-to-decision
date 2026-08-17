"""Postgres FK ordering: child stage rows require invoice_runs parent first."""

from __future__ import annotations

import json

import pytest

from app.db.database import close_db, get_connection, init_db
from app.db import repository


@pytest.fixture
def fk_db(tmp_path, monkeypatch):
    db_file = tmp_path / "fk.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("AUTO_SEED_ON_STARTUP", "false")
    from app.config import settings

    settings.database_path = str(db_file)
    settings.database_url = ""
    close_db()
    import app.db.database as db_mod

    db_mod._connection = None
    init_db()
    conn = get_connection()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    yield
    close_db()
    db_mod._connection = None


def test_stage2_save_requires_invoice_run_stub(fk_db):
    doc_id = "doc-fk-test"
    with pytest.raises(Exception):
        repository.save_match_result(
            document_id=doc_id,
            match_status="high_confidence_match",
            match_package_json=json.dumps({"invoice_id": doc_id}),
        )

    repository.ensure_invoice_run_stub(
        document_id=doc_id,
        filename="invoice.pdf",
        original_file_path="/tmp/invoice.pdf",
    )
    repository.save_match_result(
        document_id=doc_id,
        match_status="high_confidence_match",
        match_package_json=json.dumps({"invoice_id": doc_id}),
    )
    row = repository.get_match_result(doc_id)
    assert row is not None
    assert row["match_status"] == "high_confidence_match"
