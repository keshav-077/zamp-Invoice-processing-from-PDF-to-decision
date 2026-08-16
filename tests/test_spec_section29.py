"""
Spec Section 29 — required scenario tests for Final Implementation Spec.
"""

import pytest

from app.db.database import init_db, close_db, get_connection
from app.db import repository
from app.models.extraction import FieldExtraction, InvoiceExtraction, LineItem, ExtraCharge
from app.models.match import POCandidate, ScoreBreakdown, LineMapping
from app.models.verification import VerificationResult
from app.pipeline.evidence_profile import build_evidence_profile, can_run_po_resolution
from app.pipeline.reconciliation import ReconciliationEngine
from app.pipeline.router import Router
from app.pipeline.stage2.ambiguity_detector import detect_ambiguity
from app.pipeline.stage2.orchestrator import Stage2Orchestrator
from app.pipeline.stage3.extraction_field_validator import check_extraction_fields
from app.pipeline.stage3.orchestrator import Stage3Orchestrator
from app.models.match import VALIDATION_ELIGIBLE_STATES
from app.services.vendor_identity import normalize_vendor_name


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "spec29.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("AUTO_SEED_ON_STARTUP", "false")
    from app.config import settings

    settings.database_path = str(db_file)
    settings.database_url = ""
    close_db()
    import app.db.database as db_mod

    db_mod._connection = None
    init_db()
    yield
    close_db()
    db_mod._connection = None


def _vendor(name: str, vid: str):
    repository.ensure_company("DEFAULT", "Default")
    repository.upsert_vendors(
        [
            {
                "vendor_id": vid,
                "company_id": "DEFAULT",
                "name": name,
                "normalized_name": normalize_vendor_name(name),
                "aliases_json": "[]",
                "tax_id": None,
                "supplier_code": vid,
                "status": "active",
            }
        ]
    )


def _po(po_number: str, vendor_id: str, vendor_name: str, total: float, invoiced: float = 0):
    repository.upsert_purchase_orders(
        [
            {
                "po_number": po_number,
                "company_id": "DEFAULT",
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "total_amount": total,
                "currency": "USD",
                "status": "open",
                "po_type": "standard",
                "issue_date": "2026-01-01",
                "previously_invoiced": invoiced,
                "metadata_json": "{}",
            }
        ]
    )


def _extraction(**kwargs) -> InvoiceExtraction:
    defaults = {
        "vendor_name": FieldExtraction(value=None, confidence=0, status="not_found"),
        "invoice_number": FieldExtraction(value=None, confidence=0, status="not_found"),
        "invoice_date": FieldExtraction(value=None, confidence=0, status="not_found"),
        "currency": FieldExtraction(value="USD", confidence=0.99, status="extracted"),
        "total_amount": FieldExtraction(value=None, confidence=0, status="not_found"),
        "po_reference": FieldExtraction(value=None, confidence=0, status="not_found"),
        "line_items": [],
    }
    defaults.update(kwargs)
    return InvoiceExtraction(**defaults)


class TestEvidenceProfile:
    def test_no_signals(self):
        ext = _extraction()
        profile = build_evidence_profile(ext, VerificationResult(verification_status="pass"))
        assert profile.matchable_signals == []
        assert not can_run_po_resolution(profile)

    def test_vendor_or_total_any_of(self):
        ext = _extraction(
            vendor_name=FieldExtraction(value="ABC", confidence=0.9, status="extracted"),
        )
        profile = build_evidence_profile(ext, VerificationResult(verification_status="pass"))
        assert "vendor" in profile.matchable_signals
        assert Router().can_run_matching(ext, profile)


class TestSection29Matching:
    def test_3_vendor_amount_unique_po(self, tmp_db):
        _vendor("ABC Technologies", "V-ABC")
        _po("PO-101", "V-ABC", "ABC Technologies", 500000)
        ext = _extraction(
            vendor_name=FieldExtraction(value="ABC Technologies", confidence=0.95, status="extracted"),
            total_amount=FieldExtraction(value=500000, confidence=0.99, status="extracted"),
        )
        pkg = Stage2Orchestrator().match("t3", ext, suggestion_mode=True)
        assert pkg.match_status in ("matched", "high_confidence_match")
        assert len(pkg.matched_pos) == 1
        assert pkg.matched_pos[0].po_number == "PO-101"

    def test_4_vendor_amount_two_pos_ambiguous(self, tmp_db):
        _vendor("ABC Technologies", "V-ABC")
        _po("PO-101", "V-ABC", "ABC Technologies", 500000)
        _po("PO-102", "V-ABC", "ABC Technologies", 500000)
        ext = _extraction(
            vendor_name=FieldExtraction(value="ABC Technologies", confidence=0.95, status="extracted"),
            total_amount=FieldExtraction(value=500000, confidence=0.99, status="extracted"),
        )
        pkg = Stage2Orchestrator().match("t4", ext, suggestion_mode=True)
        assert pkg.match_status == "ambiguous_match"
        assert len(pkg.matched_pos) >= 2

    def test_6_vendor_only_zero_pos_unmatched(self, tmp_db):
        _vendor("Lonely Vendor", "V-LON")
        ext = _extraction(
            vendor_name=FieldExtraction(value="Lonely Vendor", confidence=0.9, status="extracted"),
        )
        pkg = Stage2Orchestrator().match("t6", ext, suggestion_mode=True)
        assert pkg.match_status in ("unmatched", "waiting_for_po", "non_po_workflow")

    def test_7_no_extraction_signals(self):
        ext = _extraction()
        profile = build_evidence_profile(ext, VerificationResult(verification_status="pass"))
        assert not Router().can_run_matching(ext, profile)

    def test_8_missing_invoice_number_validation_flag(self, tmp_db):
        _vendor("ABC Technologies", "V-ABC")
        _po("PO-101", "V-ABC", "ABC Technologies", 1000)
        ext = _extraction(
            vendor_name=FieldExtraction(value="ABC Technologies", confidence=0.95, status="extracted"),
            total_amount=FieldExtraction(value=1000, confidence=0.99, status="extracted"),
            po_reference=FieldExtraction(value="PO-101", confidence=0.99, status="extracted"),
            invoice_number=FieldExtraction(value=None, confidence=0, status="not_found"),
            invoice_date=FieldExtraction(value="2026-08-10", confidence=0.95, status="extracted"),
        )
        pkg = Stage2Orchestrator().match("t8", ext, suggestion_mode=False)
        assert pkg.match_status in VALIDATION_ELIGIBLE_STATES
        profile = build_evidence_profile(ext, VerificationResult(verification_status="pass"))
        check, codes = check_extraction_fields(ext, profile)
        assert "missing_invoice_number" in codes
        report = Stage3Orchestrator().validate("t8", ext, pkg, profile)
        assert "missing_invoice_number" in report.reason_codes or check.status == "FLAG"


class TestReconciliationSection29:
    def test_10_extra_charges_reconcile(self):
        ext = _extraction(
            subtotal=FieldExtraction(value=100000, confidence=0.99, status="extracted"),
            tax_amount=FieldExtraction(value=18000, confidence=0.99, status="extracted"),
            total_amount=FieldExtraction(value=120500, confidence=0.99, status="extracted"),
            extra_charges=[
                ExtraCharge(label="Shipping", category="shipping", amount=2000, confidence=0.9),
                ExtraCharge(label="Environmental fee", category="surcharge", amount=500, confidence=0.9),
            ],
        )
        result = ReconciliationEngine().reconcile(ext)
        assert result.overall_status in (
            "reconciled",
            "partial",
            "reconciled_with_inferred_charges",
        )

    def test_10_residual_when_fee_missing(self):
        ext = _extraction(
            subtotal=FieldExtraction(value=100000, confidence=0.99, status="extracted"),
            tax_amount=FieldExtraction(value=18000, confidence=0.99, status="extracted"),
            total_amount=FieldExtraction(value=120500, confidence=0.99, status="extracted"),
            extra_charges=[
                ExtraCharge(label="Shipping", category="shipping", amount=2000, confidence=0.9),
            ],
        )
        result = ReconciliationEngine().reconcile(ext)
        assert result.residual_amount != 0 or result.overall_status == "residual_review"


class TestAmbiguityDetectorUnit:
    def test_unique_vendor_amount_gate(self):
        top = POCandidate(
            po_number="PO-101",
            vendor_id="V1",
            score=ScoreBreakdown(vendor_match=20, amount_match=10),
            remaining_balance=500000,
        )
        status, selected = detect_ambiguity(
            [top],
            suggestion_mode=True,
            invoice_total=500000,
            invoice_currency="USD",
            po_currency="USD",
        )
        assert status == "high_confidence_match"
        assert len(selected) == 1
