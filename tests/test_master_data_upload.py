"""Tests for master data upload helpers and Postgres-safe company bootstrap."""

import inspect

import pytest
from fastapi.testclient import TestClient

from app.db.database import init_db, close_db
from app.db.seed_data import seed_database
from app.db import repository
from app.main import app
from app.services.upload_files import parse_upload_workbook, resolve_upload_extension


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("AUTO_SEED_ON_STARTUP", "false")
    from app.config import settings

    settings.database_path = str(db_file)
    settings.database_url = ""
    settings.auto_seed_on_startup = False
    close_db()
    init_db()
    seed_database()
    yield TestClient(app)
    close_db()


def test_resolve_upload_extension_prefers_excel_suffix():
    assert resolve_upload_extension("dataset.csv.xlsx") == ".xlsx"
    assert resolve_upload_extension("flat.csv") == ".csv"


def test_parse_upload_workbook_csv():
    content = b"vendor_name,po_number,po_amount\nAcme,PO-1,100\n"
    sheets = parse_upload_workbook(content, "vendors.csv")
    assert "data" in sheets
    assert len(sheets["data"]) == 1


def test_parse_upload_workbook_csv_disguised_as_xlsx():
    content = b"vendor_name,po_number,po_amount\nAcme,PO-1,100\n"
    sheets = parse_upload_workbook(content, "vendors.csv.xlsx")
    assert len(sheets["data"]) == 1


def test_ensure_company_uses_postgres_compatible_sql():
    src = inspect.getsource(repository.ensure_company)
    assert "INSERT OR IGNORE" not in src
    assert "ON CONFLICT" in src


def test_preview_master_data_double_extension(client):
    csv_content = (
        "vendor_name_on_po,po_number,po_amount,issue_date\n"
        "Double Ext Vendor,PO-EXT-1,900,2026-01-01\n"
    ).encode()
    resp = client.post(
        "/api/master-data/preview",
        files={"file": ("dataset.csv.xlsx", csv_content, "application/vnd.ms-excel")},
        params={"company_id": "DEFAULT"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["rows_analyzed"] == 1
