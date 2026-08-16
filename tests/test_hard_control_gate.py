"""
Tests for Stage 4: Hard Control Gate
"""

import pytest
from app.pipeline.stage4.decision_context import DecisionContext
from app.pipeline.stage4.hard_control_gate import evaluate_hard_controls


def _make_ctx(**overrides) -> DecisionContext:
    defaults = dict(
        invoice_id="DOC-TEST",
        validation_run_id="VR-TEST",
        validation_state="VALIDATED",
        reason_codes=[],
        controls=[],
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


class TestBlockedState:
    def test_blocked_rejects(self):
        ctx = _make_ctx(
            validation_state="BLOCKED",
            reason_codes=["DUPLICATE_CONFIRMED"],
        )
        result = evaluate_hard_controls(ctx)
        assert result.triggered
        assert result.decision == "REJECT"
        assert result.substate == "TERMINAL_REJECT"
        assert "DUPLICATE_CONFIRMED" in result.reason_codes

    def test_blocked_low_amount_still_rejects(self):
        """PRD invariant: amount cannot weaken BLOCKED."""
        ctx = _make_ctx(
            validation_state="BLOCKED",
            reason_codes=["VENDOR_BLACKLISTED"],
            amount=10.0,  # Tiny amount doesn't matter
        )
        result = evaluate_hard_controls(ctx)
        assert result.triggered
        assert result.decision == "REJECT"


class TestBlockControls:
    def test_active_block_control(self):
        ctx = _make_ctx(
            controls=[{"control_type": "BLOCK", "reason_code": "DUPLICATE_CONFIRMED"}],
        )
        result = evaluate_hard_controls(ctx)
        assert result.triggered
        assert result.decision == "REJECT"

    def test_hold_control_does_not_trigger(self):
        ctx = _make_ctx(
            controls=[{"control_type": "HOLD", "reason_code": "PRICE_VARIANCE"}],
        )
        result = evaluate_hard_controls(ctx)
        assert not result.triggered


class TestTerminalCodes:
    def test_terminal_reason_code(self):
        ctx = _make_ctx(reason_codes=["DUPLICATE_CONFIRMED"])
        result = evaluate_hard_controls(ctx)
        assert result.triggered

    def test_non_terminal_code_passes(self):
        ctx = _make_ctx(reason_codes=["PRICE_VARIANCE_EXCEEDED"])
        result = evaluate_hard_controls(ctx)
        assert not result.triggered
