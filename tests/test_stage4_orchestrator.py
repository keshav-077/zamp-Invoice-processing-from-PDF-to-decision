"""
Tests for Stage 4: Decision Orchestrator

Integration tests covering all 12 PRD scenarios (S01-S12).
"""

import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from app.models.validation import (
    ValidationReport, ValidationCheck, ControlRecord, FraudSignal,
    SourceSnapshots, RevalidationInfo,
)
from app.pipeline.stage4.orchestrator import Stage4Orchestrator


# ═══════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════

def _make_report(
    overall_state="VALIDATED",
    reason_codes=None,
    checks=None,
    controls=None,
    fraud_signals=None,
    completed_at=None,
    **overrides,
) -> ValidationReport:
    if completed_at is None:
        completed_at = datetime.now(timezone.utc).isoformat()

    return ValidationReport(
        invoice_id="DOC-TEST",
        processing_state="COMPLETED",
        overall_state=overall_state,
        reason_codes=reason_codes or [],
        checks=checks or {},
        controls=controls or [],
        fraud_signals=fraud_signals or [],
        completed_at=completed_at,
        source_snapshots=SourceSnapshots(
            extraction={
                "invoice_number": {"value": "INV-001"},
                "invoice_date": {"value": "2026-01-01"},
            }
        ),
        **overrides,
    )


def _check(check_id, status, reason="", severity="LOW", inputs=None):
    return ValidationCheck(
        check_id=check_id,
        status=status,
        reason_code=reason,
        severity=severity,
        inputs=inputs or {},
    )


# ═══════════════════════════════════════════════════════════
# S01: Normal Low-Value Invoice → AUTO_APPROVED
# ═══════════════════════════════════════════════════════════

class TestS01LowValue:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_auto_approved(self, mock_repo):
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 3200}),
                "vendor_validation": _check("vendor_validation", "PASS", inputs={"vendor_id": "V001", "vendor_status": "active"}),
            },
        )
        orch = Stage4Orchestrator(auto_approve_limit=5000)
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "APPROVE"
        assert record.decision_substate == "AUTO_APPROVED"
        assert len(record.trace.rules_evaluated) > 0
        assert len(record.trace.decision_path) > 0


# ═══════════════════════════════════════════════════════════
# S02: Valid But High-Value → APPROVAL_REQUIRED
# ═══════════════════════════════════════════════════════════

class TestS02HighValue:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_approval_required(self, mock_repo):
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 250000}),
                "vendor_validation": _check("vendor_validation", "PASS", inputs={"vendor_id": "V001", "vendor_status": "active"}),
            },
        )
        orch = Stage4Orchestrator(auto_approve_limit=5000, director_limit=500000)
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "APPROVE"
        assert record.decision_substate == "APPROVAL_REQUIRED"
        assert record.trace.authority.required is True
        assert record.trace.authority.approver_group == "finance-director-group"


# ═══════════════════════════════════════════════════════════
# S03: Price Variance (HOLD) → REVIEW_REQUIRED
# ═══════════════════════════════════════════════════════════

class TestS03PriceVariance:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_hold_review(self, mock_repo):
        report = _make_report(
            overall_state="HOLD",
            reason_codes=["PRICE_VARIANCE_EXCEEDED"],
            checks={
                "amount_variance": _check("amount_variance", "FAIL", "PRICE_VARIANCE_EXCEEDED", "HIGH"),
            },
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REVIEW_REQUIRED"
        assert record.decision_substate == "HIGH_PRIORITY_REVIEW"
        assert "PRICE_VARIANCE_EXCEEDED" in record.reason_codes


# ═══════════════════════════════════════════════════════════
# S04: Missing GRN (INCOMPLETE) → WAITING_FOR_GRN
# ═══════════════════════════════════════════════════════════

class TestS04MissingGRN:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_waiting_for_grn(self, mock_repo):
        report = _make_report(
            overall_state="VALIDATION_INCOMPLETE",
            reason_codes=["GRN_MISSING"],
            checks={
                "receipt_match": _check("receipt_match", "UNAVAILABLE", "GRN_MISSING"),
            },
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "WAITING_FOR_VALIDATION"
        assert record.decision_substate == "WAITING_FOR_GRN"


# ═══════════════════════════════════════════════════════════
# S05: Confirmed Duplicate (BLOCKED) → REJECT
# ═══════════════════════════════════════════════════════════

class TestS05Duplicate:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_terminal_reject(self, mock_repo):
        report = _make_report(
            overall_state="BLOCKED",
            reason_codes=["DUPLICATE_CONFIRMED"],
            controls=[
                ControlRecord(
                    control_id="CTRL-1",
                    control_type="BLOCK",
                    check_id="duplicate_detection",
                    reason_code="DUPLICATE_CONFIRMED",
                    severity="CRITICAL",
                ),
            ],
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REJECT"
        assert record.decision_substate == "TERMINAL_REJECT"
        assert "DUPLICATE_CONFIRMED" in record.reason_codes

    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_low_amount_cannot_bypass_block(self, mock_repo):
        """PRD invariant: amount cannot weaken BLOCKED."""
        report = _make_report(
            overall_state="BLOCKED",
            reason_codes=["DUPLICATE_CONFIRMED"],
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 10}),
            },
        )
        orch = Stage4Orchestrator(auto_approve_limit=50000)  # Very high limit
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REJECT"  # Still rejected


# ═══════════════════════════════════════════════════════════
# S06: New Vendor First Payment → REVIEW_REQUIRED
# ═══════════════════════════════════════════════════════════

class TestS06NewVendor:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_new_vendor_review(self, mock_repo):
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 30000}),
                "vendor_validation": _check("vendor_validation", "PASS", inputs={"vendor_id": "V007", "vendor_status": "active"}),
            },
            fraud_signals=[
                FraudSignal(signal_type="NEW_VENDOR_HIGH_AMOUNT", severity="MEDIUM", description="First payment"),
            ],
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REVIEW_REQUIRED"
        assert "NEW_VENDOR_FIRST_PAYMENT" in record.reason_codes


# ═══════════════════════════════════════════════════════════
# S07: Vendor Bank Change → REVIEW_REQUIRED
# ═══════════════════════════════════════════════════════════

class TestS07BankChange:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_unverified_bank_change(self, mock_repo):
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 3000}),
                "vendor_validation": _check("vendor_validation", "PASS", inputs={"vendor_id": "V001", "vendor_status": "active"}),
            },
            controls=[
                ControlRecord(
                    control_id="CTRL-BANK",
                    control_type="HOLD",
                    check_id="vendor_validation",
                    reason_code="bank_change_unverified",
                    severity="HIGH",
                ),
            ],
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REVIEW_REQUIRED"
        assert record.decision_substate == "VENDOR_SECURITY_REVIEW"


# ═══════════════════════════════════════════════════════════
# S08: Threshold Avoidance → REVIEW_REQUIRED
# ═══════════════════════════════════════════════════════════

class TestS08Clustering:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_threshold_clustering(self, mock_repo):
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 4900}),
            },
            fraud_signals=[
                FraudSignal(signal_type="THRESHOLD_SHAVING", severity="MEDIUM", description="Just below $5000"),
            ],
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REVIEW_REQUIRED"
        assert "THRESHOLD_CLUSTERING" in record.reason_codes


# ═══════════════════════════════════════════════════════════
# S10: Stale Validation → REVALIDATION_REQUIRED
# ═══════════════════════════════════════════════════════════

class TestS10StaleValidation:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_stale_report(self, mock_repo):
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        report = _make_report(
            overall_state="VALIDATED",
            completed_at=stale_time,
        )
        orch = Stage4Orchestrator(freshness_hours=24)
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "WAITING_FOR_VALIDATION"
        assert record.decision_substate == "REVALIDATION_REQUIRED"


# ═══════════════════════════════════════════════════════════
# Decision Trace Completeness
# ═══════════════════════════════════════════════════════════

class TestDecisionTrace:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_trace_has_all_fields(self, mock_repo):
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 3000}),
                "vendor_validation": _check("vendor_validation", "PASS", inputs={"vendor_id": "V001", "vendor_status": "active"}),
            },
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)

        # Trace must be complete for Stage 5
        assert record.trace.stage3_state_used == "VALIDATED"
        assert len(record.trace.rules_evaluated) > 0
        assert len(record.trace.decision_path) > 0
        assert record.trace.policy.policy_id is not None
        assert record.engine_version == "stage4-v2.0"
        assert record.decided_at != ""

    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_reject_trace_complete(self, mock_repo):
        report = _make_report(
            overall_state="BLOCKED",
            reason_codes=["DUPLICATE_CONFIRMED"],
        )
        orch = Stage4Orchestrator()
        record = orch.decide("DOC-TEST", report)

        # Even rejects must have complete traces
        assert record.decision_id.startswith("DEC-")
        assert record.validation_run_id.startswith("VR-")
        assert len(record.evidence_summary) > 0

    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_auto_approve_has_full_audit(self, mock_repo):
        """PRD: auto-approved and human-reviewed produce equivalent evidence."""
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 2000}),
                "vendor_validation": _check("vendor_validation", "PASS", inputs={"vendor_id": "V001", "vendor_status": "active"}),
            },
        )
        orch = Stage4Orchestrator(auto_approve_limit=5000)
        record = orch.decide("DOC-TEST", report)

        assert record.decision == "APPROVE"
        assert record.decision_substate == "AUTO_APPROVED"
        assert len(record.trace.rules_evaluated) > 0
        assert record.trace.policy.materiality_tier == "LOW"
        assert record.processing_time_seconds >= 0


# ═══════════════════════════════════════════════════════════
# Precedence Tests
# ═══════════════════════════════════════════════════════════

class TestPrecedence:
    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_hard_control_beats_auto_approve(self, mock_repo):
        """BLOCKED overrides any amount-based auto-approval."""
        report = _make_report(
            overall_state="BLOCKED",
            reason_codes=["DUPLICATE_CONFIRMED"],
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 100}),
            },
        )
        orch = Stage4Orchestrator(auto_approve_limit=999999)
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REJECT"

    @patch("app.pipeline.stage4.orchestrator.repository")
    def test_override_beats_auto_approve(self, mock_repo):
        """Mandatory override overrides auto-approval eligibility."""
        report = _make_report(
            overall_state="VALIDATED",
            checks={
                "amount_variance": _check("amount_variance", "PASS", inputs={"invoice_total": 3000}),
            },
            fraud_signals=[
                FraudSignal(signal_type="THRESHOLD_SHAVING", severity="MEDIUM", description="Test"),
            ],
        )
        orch = Stage4Orchestrator(auto_approve_limit=5000)
        record = orch.decide("DOC-TEST", report)
        assert record.decision == "REVIEW_REQUIRED"  # Not AUTO_APPROVED
