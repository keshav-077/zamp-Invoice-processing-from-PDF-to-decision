"""
Tests for Stage 4: Mandatory Override Layer
"""

import pytest
from app.pipeline.stage4.decision_context import DecisionContext
from app.pipeline.stage4.mandatory_overrides import evaluate_overrides


def _make_ctx(**overrides) -> DecisionContext:
    defaults = dict(
        invoice_id="DOC-TEST",
        validation_run_id="VR-TEST",
        validation_state="VALIDATED",
        amount=5000.0,
        vendor_id="V001",
        is_first_payment=False,
        bank_change_detected=False,
        bank_change_verified=False,
        fraud_signals=[],
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


class TestBankChange:
    def test_unverified_bank_change(self):
        ctx = _make_ctx(bank_change_detected=True, bank_change_verified=False)
        result = evaluate_overrides(ctx)
        assert result.triggered
        assert result.substate == "VENDOR_SECURITY_REVIEW"
        assert "UNVERIFIED_BANK_CHANGE" in result.reason_codes

    def test_verified_bank_change_passes(self):
        ctx = _make_ctx(bank_change_detected=True, bank_change_verified=True)
        result = evaluate_overrides(ctx)
        # Bank change verified should not trigger bank override
        bank_triggered = "UNVERIFIED_BANK_CHANGE" in (result.reason_codes or [])
        assert not bank_triggered

    def test_no_bank_change(self):
        ctx = _make_ctx()
        result = evaluate_overrides(ctx)
        assert not result.triggered


class TestNewVendor:
    def test_first_payment_above_threshold(self):
        ctx = _make_ctx(is_first_payment=True, amount=15000.0)
        result = evaluate_overrides(ctx)
        assert result.triggered
        assert "NEW_VENDOR_FIRST_PAYMENT" in result.reason_codes

    def test_first_payment_below_threshold(self):
        ctx = _make_ctx(is_first_payment=True, amount=5000.0)
        result = evaluate_overrides(ctx)
        # Below threshold → should not trigger new vendor override
        new_vendor_triggered = "NEW_VENDOR_FIRST_PAYMENT" in (result.reason_codes or [])
        assert not new_vendor_triggered

    def test_not_first_payment(self):
        ctx = _make_ctx(is_first_payment=False, amount=100000.0)
        result = evaluate_overrides(ctx)
        new_vendor_triggered = "NEW_VENDOR_FIRST_PAYMENT" in (result.reason_codes or [])
        assert not new_vendor_triggered


class TestClustering:
    def test_threshold_shaving_signal(self):
        ctx = _make_ctx(
            fraud_signals=[{"signal_type": "THRESHOLD_SHAVING", "severity": "MEDIUM"}]
        )
        result = evaluate_overrides(ctx)
        assert result.triggered
        assert "THRESHOLD_CLUSTERING" in result.reason_codes
        assert result.substate == "FRAUD_REVIEW"


class TestHighFraud:
    def test_critical_fraud_signal(self):
        ctx = _make_ctx(
            fraud_signals=[{"signal_type": "SUSPICIOUS_PATTERN", "severity": "CRITICAL"}]
        )
        result = evaluate_overrides(ctx)
        assert result.triggered
        assert "HIGH_FRAUD_SIGNAL" in result.reason_codes
        assert result.substate == "FRAUD_REVIEW"
