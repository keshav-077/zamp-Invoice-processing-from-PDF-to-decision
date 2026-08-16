"""
Tests for Stage 3: Fraud & Anomaly Signal Generator
"""

import pytest
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.stage3.fraud_detector import (
    detect_fraud_signals,
    _is_suspiciously_round,
    _check_threshold_shaving,
)


def _make_ctx(**overrides) -> ValidationContext:
    defaults = dict(
        document_id="DOC-TEST",
        approval_thresholds=[10000, 25000, 50000],
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


class TestRoundNumber:
    def test_round_thousand(self):
        assert _is_suspiciously_round(5000.0) is True

    def test_round_five_hundred(self):
        assert _is_suspiciously_round(7500.0) is True

    def test_not_round(self):
        assert _is_suspiciously_round(5432.10) is False

    def test_small_amount(self):
        assert _is_suspiciously_round(500.0) is False


class TestThresholdShaving:
    def test_just_below_threshold(self):
        result = _check_threshold_shaving(9800, [10000, 25000])
        assert result is not None
        threshold, distance = result
        assert threshold == 10000
        assert distance == 200

    def test_well_below_threshold(self):
        result = _check_threshold_shaving(8000, [10000, 25000])
        assert result is None

    def test_above_threshold(self):
        result = _check_threshold_shaving(11000, [10000, 25000])
        assert result is None


class TestFraudCheck:
    def test_no_signals(self):
        ctx = _make_ctx(total_amount=5432.10, invoice_number="INV-2026-001")
        check, signals = detect_fraud_signals(ctx)
        assert check.status == "PASS"
        assert len(signals) == 0

    def test_round_number_signal(self):
        ctx = _make_ctx(total_amount=10000.0, invoice_number="INV-2026-001")
        check, signals = detect_fraud_signals(ctx)
        round_sigs = [s for s in signals if s.signal_type == "ROUND_NUMBER"]
        assert len(round_sigs) == 1

    def test_new_vendor_high_amount(self):
        ctx = _make_ctx(
            total_amount=30000.0,
            matched_vendor_id="V007",
            invoice_number="INV-001",
        )
        check, signals = detect_fraud_signals(ctx)
        nv_sigs = [s for s in signals if s.signal_type == "NEW_VENDOR_HIGH_AMOUNT"]
        assert len(nv_sigs) == 1
        assert check.status == "FLAG"
