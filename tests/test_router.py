"""
InvoiceFlow AI — Router Tests

Tests routing decision logic for all three outcomes:
- STAGE1_PASSED
- NEEDS_HUMAN_REVIEW
- Various flag triggers
"""

import pytest
from app.models.extraction import InvoiceExtraction, FieldExtraction, LineItem
from app.models.verification import VerificationResult, VerificationIssue
from app.models.arithmetic import ArithmeticResult, ArithmeticCheck
from app.models.reconciliation import ReconciliationResult, ReconciliationCheck
from app.pipeline.router import Router
from app.pipeline.evidence_profile import build_evidence_profile


_MISSING = object()


def _route(router, extraction, verification, arithmetic, reconciliation=_MISSING):
    """Production path: always include evidence profile."""
    recon = make_passing_reconciliation() if reconciliation is _MISSING else reconciliation
    profile = build_evidence_profile(extraction, verification, recon)
    return router.route(
        extraction=extraction,
        verification=verification,
        arithmetic=arithmetic,
        reconciliation=recon,
        evidence_profile=profile,
    )


def make_field(value, confidence=0.98, status="extracted"):
    return FieldExtraction(value=value, confidence=confidence, status=status)


def make_passing_extraction():
    """Create an extraction that should pass all checks."""
    return InvoiceExtraction(
        vendor_name=make_field("Acme Corp", 0.95),
        invoice_number=make_field("INV-001", 0.98),
        invoice_date=make_field("2026-01-15", 0.95),
        due_date=make_field("2026-02-15", 0.80),
        po_reference=make_field("PO-100", 0.75),
        currency=make_field("USD", 0.99),
        subtotal=make_field(1000.0, 0.96),
        tax_amount=make_field(80.0, 0.96),
        total_amount=make_field(1080.0, 0.98),
        line_items=[],
    )


def make_passing_verification():
    return VerificationResult(
        verification_status="pass",
        overall_confidence=0.95,
        issues=[],
    )


def make_passing_arithmetic():
    return ArithmeticResult(
        overall_status="pass",
        checks=[
            ArithmeticCheck(check_name="subtotal_plus_tax", status="pass", detail="OK"),
        ],
    )


def make_passing_reconciliation():
    return ReconciliationResult(
        overall_status="reconciled",
        checks=[
            ReconciliationCheck(
                check_name="primary_total_reconciliation",
                status="pass",
                detail="OK",
            ),
        ],
    )


class TestStage1Passed:
    """Invoice should pass when all signals agree."""

    def test_all_passing(self):
        router = Router()
        decision = _route(
            router,
            make_passing_extraction(),
            make_passing_verification(),
            make_passing_arithmetic(),
        )
        assert decision.status == "stage1_passed"

    def test_missing_po_reference_still_passes_when_approval_ok(self):
        ext = make_passing_extraction()
        ext.po_reference = make_field(None, 0.0, "not_found")
        ext.line_items = [
            LineItem(description="Item", amount=100.0, confidence=0.95),
        ]
        router = Router()
        profile = build_evidence_profile(
            ext, make_passing_verification(), make_passing_reconciliation()
        )
        decision = router.route(
            ext,
            make_passing_verification(),
            make_passing_arithmetic(),
            make_passing_reconciliation(),
            evidence_profile=profile,
        )
        assert decision.status == "stage1_passed"
        assert router.can_run_matching(ext, profile)


class TestNeedsHumanReview:
    """Invoice should flag for review when signals disagree."""

    def test_low_confidence_critical_field(self):
        ext = make_passing_extraction()
        ext.total_amount = make_field(1080.0, 0.50)  # Below 0.97 threshold
        router = Router()
        decision = _route(router, ext, make_passing_verification(), make_passing_arithmetic())
        assert decision.status == "needs_human_review"

    def test_missing_invoice_number_does_not_block_when_other_fields_ok(self):
        ext = make_passing_extraction()
        ext.invoice_number = make_field(None, 0.0, "not_found")
        router = Router()
        decision = _route(router, ext, make_passing_verification(), make_passing_arithmetic())
        assert decision.status == "stage1_passed"

    def test_uncertain_critical_field(self):
        ext = make_passing_extraction()
        ext.vendor_name = make_field("Acme?", 0.60, "uncertain")
        router = Router()
        decision = _route(router, ext, make_passing_verification(), make_passing_arithmetic())
        assert decision.status == "needs_human_review"

    def test_verification_flagged(self):
        verification = VerificationResult(
            verification_status="flag",
            overall_confidence=0.70,
            issues=[
                VerificationIssue(field="total_amount", severity="high", reason="Mismatch"),
            ],
        )
        router = Router()
        decision = _route(
            router, make_passing_extraction(), verification, make_passing_arithmetic()
        )
        assert decision.status == "needs_human_review"

    def test_expiry_date_label_does_not_block(self):
        verification = VerificationResult(
            verification_status="flag",
            overall_confidence=0.92,
            issues=[
                VerificationIssue(
                    field="due_date",
                    severity="high",
                    reason="The date '1992-09-14' is labeled as 'Expiry Date' in the document, not a due date.",
                ),
            ],
        )
        router = Router()
        decision = _route(
            router, make_passing_extraction(), verification, make_passing_arithmetic()
        )
        assert decision.status == "stage1_passed"

    def test_inferred_currency_at_90_passes(self):
        ext = make_passing_extraction()
        ext.currency = make_field("USD", 0.90, "inferred")
        router = Router()
        decision = _route(router, ext, make_passing_verification(), make_passing_arithmetic())
        assert decision.status == "stage1_passed"

    def test_verification_unavailable(self):
        verification = VerificationResult(
            verification_status="unavailable",
            overall_confidence=0.0,
            issues=[],
        )
        router = Router()
        decision = _route(
            router, make_passing_extraction(), verification, make_passing_arithmetic()
        )
        assert decision.status == "needs_human_review"

    def test_arithmetic_failure(self):
        arithmetic = ArithmeticResult(
            overall_status="fail",
            checks=[
                ArithmeticCheck(
                    check_name="subtotal_plus_tax",
                    status="fail",
                    detail="1000 + 80 = 1080 ≠ 1200",
                ),
            ],
        )
        router = Router()
        decision = _route(
            router,
            make_passing_extraction(),
            make_passing_verification(),
            arithmetic,
            reconciliation=None,
        )
        assert decision.status == "needs_human_review"


class TestExplanations:
    """Decision explanations should be human-readable."""

    def test_passing_has_explanations(self):
        router = Router()
        decision = _route(
            router,
            make_passing_extraction(),
            make_passing_verification(),
            make_passing_arithmetic(),
        )
        assert len(decision.explanations) > 0

    def test_flagged_explains_reason(self):
        ext = make_passing_extraction()
        ext.total_amount = make_field(1080.0, 0.50)
        router = Router()
        decision = _route(router, ext, make_passing_verification(), make_passing_arithmetic())
        # Should mention confidence or threshold
        assert any("confidence" in e.lower() or "threshold" in e.lower() for e in decision.explanations)
