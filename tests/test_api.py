"""API integration tests for InvoiceFlow AI."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import init_db, close_db
from app.db.seed_data import seed_database


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


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_list_invoices_empty(client):
    resp = client.get("/api/invoices")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 0


def test_job_not_found(client):
    resp = client.get("/api/jobs/JOB-NOTFOUND")
    assert resp.status_code == 404


def test_blob_token_not_configured(client):
    resp = client.get("/api/blob/upload-token")
    assert resp.status_code == 501


def test_import_returns_422_when_review_needed(client):
    csv_content = (
        "vendor_name_on_po,po_num_x,amount_usd,issued\n"
        "Review Vendor LLC,PO-API-1,1500,2026-01-01\n"
    ).encode()
    resp = client.post(
        "/api/master-data/import",
        files={"file": ("needs_review.csv", csv_content, "text/csv")},
        params={"company_id": "DEFAULT"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail.get("review_needed") is True


def test_upload_async_returns_job_id(client):
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000050001b8b82f0000000049454e44ae426082"
    )
    resp = client.post(
        "/api/upload/async",
        files={"file": ("invoice.png", png, "image/png")},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"].startswith("JOB-")
    assert body["status"] == "queued"


def test_upload_async_rejects_bad_extension(client):
    resp = client.post(
        "/api/upload/async",
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert isinstance(detail, str) and detail.strip()


def test_import_confirm_succeeds_after_mappings(client):
    csv_content = (
        "vendor_name_on_po,po_number,po_amount,issue_date\n"
        "Confirm Vendor LLC,PO-API-2,800,2026-01-01\n"
    ).encode()
    preview = client.post(
        "/api/master-data/preview",
        files={"file": ("confirm.csv", csv_content, "text/csv")},
        params={"company_id": "DEFAULT"},
    )
    assert preview.status_code == 200
    sheets = preview.json()["preview"]["profile"]["sheets"]
    import json

    resp = client.post(
        "/api/master-data/import/confirm",
        files={"file": ("confirm.csv", csv_content, "text/csv")},
        data={"mappings": json.dumps({"sheets": sheets})},
        params={"company_id": "DEFAULT"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("valid") or body.get("partial_success")
    assert not body.get("review_needed")
