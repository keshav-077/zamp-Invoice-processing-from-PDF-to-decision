"""Unit tests for deterministic row-level classification."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.services.adaptive_importer import AdaptiveImporter, _rows_from_profile
from app.services.import_profiler import profile_workbook
from app.services.row_classifier import classify_row


def test_invoice_row_none_po_is_transaction():
    row = {
        "vendor_name_on_invoice": "Acme Corp",
        "invoice_number": "INV-001",
        "invoice_total": 5000,
        "po_number": "NONE",
    }
    result = classify_row(row)
    assert result.record_type == "invoice_transaction"
    assert result.po_reference is None


def test_valid_po_row_is_purchase_order():
    row = {
        "vendor_name": "Acme",
        "po_number": "PO-123",
        "po_amount": 5000,
        "po_status": "open",
    }
    result = classify_row(row)
    assert result.record_type == "purchase_order"
    assert result.po_reference == "PO-123"


def test_invoice_with_po_reference():
    row = {
        "vendor_name_on_invoice": "Acme",
        "invoice_number": "INV-2",
        "invoice_total": 1000,
        "po_number": "PO-456",
    }
    result = classify_row(row)
    assert result.record_type == "invoice_with_po_reference"
    assert result.po_reference == "PO-456"


def test_flat_record_type_explicit():
    row = {"record_type": "vendor", "name": "Test Vendor", "vendor_id": "V99"}
    result = classify_row(row, explicit_record_type="vendor")
    assert result.record_type == "vendor"
    assert result.confidence == 1.0


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("AUTO_SEED_ON_STARTUP", "false")
    from app.config import settings

    settings.database_path = str(db_file)
    settings.database_url = ""
    from app.db.database import close_db, init_db
    import app.db.database as db_mod

    close_db()
    db_mod._connection = None
    init_db()
    yield db_file
    close_db()
    db_mod._connection = None


def test_mixed_csv_stages_invoice_and_po(tmp_db):
    rows = pd.DataFrame(
        [
            {
                "vendor_name_on_invoice": "Acme",
                "invoice_number": "INV-1",
                "invoice_subtotal": 100,
                "po_number": "NONE",
            },
            {
                "vendor_name_on_invoice": "Beta Inc",
                "po_number": "PO-MIX-1",
                "po_amount": 2500,
                "po_status": "open",
            },
        ]
    )
    buf = io.BytesIO()
    rows.to_csv(buf, index=False)
    content = buf.getvalue()
    profile = profile_workbook(content, "mixed.csv")
    staged = _rows_from_profile(content, "mixed.csv", {"sheets": profile["sheets"], "flat_mode": profile["flat_mode"], "saved_profile": None})
    entities = {s["record_type"] for s in staged}
    assert "invoice_transaction" in entities
    assert "purchase_order" in entities
    assert len(staged) == 2


def test_mixed_import_creates_source_records(tmp_db):
    rows = pd.DataFrame(
        [
            {
                "vendor_name_on_invoice": "Txn Co",
                "invoice_number": "INV-TX-1",
                "invoice_subtotal": 500,
                "po_number": "NONE",
            },
            {
                "vendor_name_on_invoice": "PO Co",
                "po_number": "PO-TX-1",
                "po_amount": 1200,
                "issue_date": "2026-01-01",
            },
        ]
    )
    buf = io.BytesIO()
    rows.to_csv(buf, index=False)
    content = buf.getvalue()
    result = AdaptiveImporter().commit(content, "mixed.csv")
    assert result.get("partial_success") or result.get("valid"), result.get("errors")
    assert result["summary"]["source_records"] >= 1
    assert result["summary"]["purchase_orders"] >= 1
    assert "classification_summary" in result
