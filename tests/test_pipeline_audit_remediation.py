"""Regression tests for pipeline audit remediation (Stages 1–3, import gates)."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.db.database import init_db, close_db
from app.db import repository
from app.models.match import POCandidate, ScoreBreakdown
from app.pipeline.stage2.ambiguity_detector import detect_ambiguity
from app.pipeline.stage3.contract_gate import validate_contract
from app.models.match import MatchPackage
from app.services.adaptive_importer import AdaptiveImporter
from app.services.vendor_identity import normalize_vendor_name


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


def test_vendor_amount_no_po_auto_match():
    """No-PO invoice with strong vendor+amount and single open PO auto-matches."""
    candidate = POCandidate(
        po_number="PO-9011",
        vendor_id="V1",
        vendor_name="Harrington Supplies",
        score=ScoreBreakdown(vendor_match=18, amount_match=10, line_match=0, total=51),
        remaining_balance=10000.0,
        line_mappings=[],
    )
    status, selected = detect_ambiguity(
        [candidate],
        suggestion_mode=True,
        invoice_total=332.0,
        po_presence="non_po",
    )
    assert status == "high_confidence_match"
    assert len(selected) == 1
    assert selected[0].po_number == "PO-9011"


def test_contract_gate_blocks_unconfirmed_suggestion():
    pkg = MatchPackage(
        invoice_id="doc-1",
        match_status="suggested_po_match",
        suggestion_mode=True,
        match_provenance="suggestion",
        matched_pos=[],
    )
    gate = validate_contract("doc-1", pkg)
    assert not gate.is_valid or gate.validation_mode == "none"


def test_contract_gate_allows_confirmed_high_confidence():
    pkg = MatchPackage(
        invoice_id="doc-1",
        match_status="high_confidence_match",
        suggestion_mode=False,
        match_provenance="auto",
        matched_pos=[
            POCandidate(
                po_number="PO-9011",
                vendor_id="V1",
                score=ScoreBreakdown(vendor_match=18, amount_match=10, total=90),
            )
        ],
    )
    gate = validate_contract("doc-1", pkg)
    assert gate.is_valid
    assert gate.validation_mode == "full"


def test_commit_blocked_when_review_needed(tmp_db):
    rows = pd.DataFrame(
        {
            "vendor_name_on_po": ["Review Vendor LLC"],
            "po_num_x": ["PO-REV-1"],
            "amount_usd": [1200],
            "issued": ["2026-01-01"],
        }
    )
    buf = io.BytesIO()
    rows.to_csv(buf, index=False)
    content = buf.getvalue()

    imp = AdaptiveImporter()
    preview = imp.preview(content, "needs_review.csv")
    assert preview.get("review_needed"), preview

    result = imp.commit(content, "needs_review.csv")
    assert result.get("review_needed")
    assert not result.get("valid")


def test_flat_csv_confirm_matches_sheet_and_entity(tmp_db):
    """Confirmed mappings apply only to the matching (sheet, entity) pair."""
    rows = pd.DataFrame(
        {
            "vendor_name_on_po": ["Entity A Vendor"],
            "po_number": ["PO-A-1"],
            "po_amount": [500],
            "issue_date": ["2026-01-01"],
        }
    )
    buf = io.BytesIO()
    rows.to_csv(buf, index=False)
    content = buf.getvalue()

    imp = AdaptiveImporter()
    preview = imp.preview(content, "flat.csv")
    sheets = preview["preview"]["profile"]["sheets"]
    assert sheets

    target = sheets[0]
    confirmed = [
        {
            "sheet": target["sheet"],
            "entity": "wrong_entity",
            "column_mappings": target.get("column_mappings", []),
        },
        {
            "sheet": target["sheet"],
            "entity": target.get("entity"),
            "column_mappings": target.get("column_mappings", []),
        },
    ]
    result = imp.commit(content, "flat.csv", confirmed_mappings=confirmed)
    assert not result.get("review_needed"), result
    assert result.get("valid") or result.get("partial_success"), result.get("errors")


def test_source_record_vendor_normalize_on_hint(tmp_db):
    company_id = "DEFAULT"
    repository.upsert_source_records(
        [
            {
                "source_record_id": "sr-hint-1",
                "company_id": company_id,
                "record_type": "invoice_transaction",
                "vendor_name": "Acme Corporation Inc.",
                "invoice_number": "INV-HINT-1",
                "po_reference": "PO-HINT-99",
                "status": "ready",
            }
        ]
    )
    hits = repository.search_source_records_by_invoice_number(
        "INV-HINT-1",
        vendor_name="ACME CORP",
        company_id=company_id,
    )
    assert len(hits) == 1
    assert hits[0]["po_reference"] == "PO-HINT-99"
    assert normalize_vendor_name(hits[0]["vendor_name"]) == normalize_vendor_name("ACME CORP")
