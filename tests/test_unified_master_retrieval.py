"""Unified master data: user CSV mirrored to purchase_orders equals seed PO master."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.db.database import init_db, close_db
from app.db import repository
from app.models.extraction import FieldExtraction, InvoiceExtraction, LineItem
from app.models.verification import VerificationResult
from app.pipeline.evidence_profile import build_evidence_profile
from app.pipeline.stage2.orchestrator import Stage2Orchestrator
from app.pipeline.stage2.ambiguity_detector import detect_ambiguity
from app.models.match import POCandidate, ScoreBreakdown
from app.services.adaptive_importer import AdaptiveImporter
from app.services.import_po_mirror import build_mirrored_po_row, mirrored_po_number
from scripts.sync_source_records_to_po_master import sync_company


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("AUTO_SEED_ON_STARTUP", "false")
    from app.config import settings

    settings.database_path = str(db_file)
    settings.database_url = ""
    close_db()
    import app.db.database as db_mod

    db_mod._connection = None
    init_db()
    yield db_file
    close_db()
    db_mod._connection = None


def test_mirrored_po_number_without_ref():
    assert mirrored_po_number("abc123", None) == "IMP-abc123"


def test_mirrored_po_number_with_ref():
    assert mirrored_po_number("abc123", "PO-5001") == "PO-5001"


def test_import_csv_mirrors_to_purchase_orders(tmp_db):
    rows = pd.DataFrame(
        {
            "vendor_name_on_invoice": ["Harrington Kline and Butler"],
            "invoice_number": ["447295"],
            "invoice_total": [332.8],
            "invoice_date": ["2011-08-23"],
        }
    )
    buf = io.BytesIO()
    rows.to_csv(buf, index=False)
    content = buf.getvalue()

    imp = AdaptiveImporter()
    preview = imp.preview(content, "transactions.csv")
    sheets = preview["preview"]["profile"]["sheets"]
    result = imp.commit(content, "transactions.csv", confirmed_mappings=sheets)

    assert result.get("valid") or result.get("partial_success"), result.get("errors")
    pos = repository.get_all_open_pos()
    assert len(pos) >= 1
    harrington = [p for p in pos if "Harrington" in (p.get("vendor_name") or "")]
    assert harrington
    assert harrington[0]["metadata"].get("import_derived") is True
    assert harrington[0]["total_amount"] == 332.8

    src = repository.get_source_records_by_company()
    assert len(src) >= 1


def test_sync_source_records_backfill(tmp_db):
    repository.upsert_source_records(
        [
            {
                "source_record_id": "sr-backfill-1",
                "company_id": "DEFAULT",
                "record_type": "invoice_transaction",
                "vendor_name": "Mirror Test Vendor",
                "invoice_number": "INV-99",
                "invoice_total": 500.0,
                "currency": "USD",
                "status": "active",
                "created_at": "2026-01-01T00:00:00",
            }
        ]
    )
    out = sync_company("DEFAULT")
    assert out["mirrored"] == 1
    po = repository.get_po("IMP-sr-backfill-1")
    assert po is not None
    assert po["total_amount"] == 500.0
    assert po["metadata"]["import_derived"] is True


def test_ensure_vendor_for_mirror_rejects_mismatched_vendor_id(tmp_db):
    """Do not reuse vendor_id when CSV vendor_name disagrees with master row."""
    from app.services.import_po_mirror import ensure_vendor_for_mirror
    from app.services.adaptive_importer import _ensure_vendor_row

    vendor_by_id = {
        "V020": {
            "vendor_id": "V020",
            "name": "Oconnor Fuller and Carter",
            "normalized_name": "OCONNOR FULLER CARTER",
        }
    }
    vendor_rows: list[dict] = []
    vid = ensure_vendor_for_mirror(
        "DEFAULT",
        "V020",
        "Harrington Kline and Butler",
        vendor_by_id,
        {},
        {},
        {},
        vendor_rows,
        {},
        _ensure_vendor_row,
    )
    assert vid != "V020"
    assert vid is not None
    assert any("Harrington" in v["name"] for v in vendor_rows)


def test_harrington_stage2_high_confidence_after_mirror(tmp_db):
    repository.upsert_vendors(
        [
            {
                "vendor_id": "V001",
                "company_id": "DEFAULT",
                "name": "Harrington, Kline and Butler",
                "normalized_name": "harrington kline and butler",
                "aliases_json": "[]",
                "status": "active",
            }
        ]
    )
    repository.upsert_purchase_orders(
        [
            {
                "po_number": "IMP-harrington1",
                "company_id": "DEFAULT",
                "vendor_id": "V001",
                "vendor_name": "Harrington, Kline and Butler",
                "total_amount": 332.8,
                "currency": "USD",
                "status": "open",
                "po_type": "blanket",
                "issue_date": "2011-08-23",
                "metadata_json": '{"import_derived": true, "source_record_id": "harrington1"}',
            }
        ]
    )

    extraction = InvoiceExtraction(
        vendor_name=FieldExtraction(value="Harrington, Kline and Butler", confidence=0.95),
        invoice_number=FieldExtraction(value="447295", confidence=0.98),
        invoice_date=FieldExtraction(value="2011-08-23", confidence=0.95),
        currency=FieldExtraction(value="USD", confidence=0.99),
        total_amount=FieldExtraction(value=332.8, confidence=0.98),
        po_reference=FieldExtraction(value=None, confidence=0.0, status="not_found"),
        line_items=[LineItem(description="Item", amount=100.0, confidence=0.9)],
    )
    verification = VerificationResult(verification_status="pass", overall_confidence=0.95)
    profile = build_evidence_profile(extraction, verification, None)

    stage2 = Stage2Orchestrator()
    pkg = stage2.match(
        "doc-test",
        extraction,
        suggestion_mode=True,
        evidence_profile=profile,
    )
    assert pkg.match_status == "high_confidence_match"
    assert len(pkg.matched_pos) == 1
    assert pkg.matched_pos[0].import_derived is True
    assert pkg.vendor_master_status in ("master_hit", "po_aligned")


def test_vendor_amount_no_po_auto_match_on_import_po():
    candidate = POCandidate(
        po_number="IMP-abc",
        vendor_id="V1",
        vendor_name="Harrington, Kline and Butler",
        score=ScoreBreakdown(vendor_match=18, amount_match=10, line_match=0, total=51),
        remaining_balance=332.8,
        retrieval_method="import_derived",
        import_derived=True,
    )
    status, selected = detect_ambiguity(
        [candidate],
        suggestion_mode=True,
        invoice_total=332.8,
        po_presence="non_po",
    )
    assert status == "high_confidence_match"
    assert len(selected) == 1
