"""
Tests for Stage 3: Control & Aggregation Policy Engine
"""

import pytest
from app.models.validation import ValidationCheck, FraudSignal
from app.pipeline.stage3.control_aggregator import aggregate_controls


def _check(check_id, status, reason="", severity="LOW"):
    return ValidationCheck(
        check_id=check_id,
        status=status,
        reason_code=reason,
        severity=severity,
    )


class TestAllPass:
    def test_all_checks_pass(self):
        checks = {
            "amount_variance": _check("amount_variance", "PASS"),
            "tax_validation": _check("tax_validation", "PASS"),
            "duplicate_detection": _check("duplicate_detection", "PASS"),
            "vendor_validation": _check("vendor_validation", "PASS"),
            "receipt_match": _check("receipt_match", "PASS"),
            "budget_tolerance": _check("budget_tolerance", "PASS"),
            "fraud_signals": _check("fraud_signals", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "VALIDATED"
        assert len(controls) == 0

    def test_not_applicable_treated_as_pass(self):
        checks = {
            "amount_variance": _check("amount_variance", "NOT_APPLICABLE"),
            "tax_validation": _check("tax_validation", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "VALIDATED"


class TestBlocked:
    def test_duplicate_confirmed_blocks(self):
        checks = {
            "duplicate_detection": _check("duplicate_detection", "FAIL", "DUPLICATE_CONFIRMED", "CRITICAL"),
            "amount_variance": _check("amount_variance", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "BLOCKED"
        assert "DUPLICATE_CONFIRMED" in reasons
        assert len(controls) == 1
        assert controls[0].control_type == "BLOCK"


class TestHold:
    def test_price_variance_creates_hold(self):
        checks = {
            "amount_variance": _check("amount_variance", "FAIL", "PRICE_VARIANCE_EXCEEDED", "HIGH"),
            "tax_validation": _check("tax_validation", "PASS"),
            "vendor_validation": _check("vendor_validation", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "HOLD"
        assert "PRICE_VARIANCE_EXCEEDED" in reasons

    def test_budget_exceeded_creates_hold(self):
        checks = {
            "budget_tolerance": _check("budget_tolerance", "FAIL", "BUDGET_EXCEEDED", "HIGH"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "HOLD"


class TestValidationIncomplete:
    def test_unavailable_check(self):
        checks = {
            "receipt_match": _check("receipt_match", "UNAVAILABLE", "GRN_MISSING"),
            "amount_variance": _check("amount_variance", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "VALIDATION_INCOMPLETE"
        assert "GRN_MISSING" in reasons


class TestReviewRequired:
    def test_flag_triggers_review(self):
        checks = {
            "vendor_validation": _check("vendor_validation", "FLAG", "VENDOR_REVIEW_REQUIRED"),
            "amount_variance": _check("amount_variance", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "REVIEW_REQUIRED"

    def test_ambiguous_match_triggers_review(self):
        checks = {
            "amount_variance": _check("amount_variance", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "ambiguous_match")
        assert state == "REVIEW_REQUIRED"
        assert "AMBIGUOUS_PO_MATCH" in reasons

    def test_medium_fraud_triggers_review(self):
        checks = {
            "fraud_signals": _check("fraud_signals", "PASS"),
        }
        fraud_signals = [
            FraudSignal(signal_type="THRESHOLD_SHAVING", severity="MEDIUM", description="Test")
        ]
        state, reasons, controls = aggregate_controls(checks, fraud_signals, "matched")
        assert state == "REVIEW_REQUIRED"


class TestPrecedence:
    def test_block_overrides_hold(self):
        """6 PASSes cannot cancel a blocking failure."""
        checks = {
            "duplicate_detection": _check("duplicate_detection", "FAIL", "DUPLICATE_CONFIRMED", "CRITICAL"),
            "amount_variance": _check("amount_variance", "FAIL", "PRICE_VARIANCE_EXCEEDED", "HIGH"),
            "tax_validation": _check("tax_validation", "PASS"),
            "vendor_validation": _check("vendor_validation", "PASS"),
            "receipt_match": _check("receipt_match", "PASS"),
            "budget_tolerance": _check("budget_tolerance", "PASS"),
        }
        state, reasons, controls = aggregate_controls(checks, [], "matched")
        assert state == "BLOCKED"  # Not HOLD, not VALIDATED
