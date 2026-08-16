"""
Tests for Stage 4: Policy Engine (Steps 4-6)
"""

import pytest
from app.pipeline.stage4.decision_context import DecisionContext
from app.pipeline.stage4.policy_engine import evaluate_policy, _resolve_policy, _map_stage3_state


def _make_ctx(**overrides) -> DecisionContext:
    defaults = dict(
        invoice_id="DOC-TEST",
        validation_run_id="VR-TEST",
        validation_state="VALIDATED",
        reason_codes=[],
        amount=5000.0,
        vendor_id="V001",
        vendor_status="active",
        vendor_risk_tier="STANDARD",
        is_first_payment=False,
        source_snapshots={
            "extraction": {
                "invoice_number": {"value": "INV-001"},
                "invoice_date": {"value": "2026-01-01"},
            }
        },
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


class TestStage3StateMapping:
    def test_hold_maps_to_review(self):
        ctx = _make_ctx(validation_state="HOLD", reason_codes=["PRICE_VARIANCE_EXCEEDED"])
        decision, substate, reasons, rule = _map_stage3_state(ctx)
        assert decision == "REVIEW_REQUIRED"
        assert substate == "HIGH_PRIORITY_REVIEW"

    def test_review_required_maps_to_review(self):
        ctx = _make_ctx(validation_state="REVIEW_REQUIRED", reason_codes=["VENDOR_REVIEW_REQUIRED"])
        decision, substate, reasons, rule = _map_stage3_state(ctx)
        assert decision == "REVIEW_REQUIRED"
        assert substate == "STANDARD_REVIEW"

    def test_incomplete_grn_missing(self):
        ctx = _make_ctx(validation_state="VALIDATION_INCOMPLETE", reason_codes=["GRN_MISSING"])
        decision, substate, reasons, rule = _map_stage3_state(ctx)
        assert decision == "WAITING_FOR_VALIDATION"
        assert substate == "WAITING_FOR_GRN"

    def test_incomplete_other(self):
        ctx = _make_ctx(validation_state="VALIDATION_INCOMPLETE", reason_codes=["BUDGET_SERVICE_DOWN"])
        decision, substate, reasons, rule = _map_stage3_state(ctx)
        assert decision == "WAITING_FOR_VALIDATION"
        assert substate == "WAITING_FOR_REQUIRED_DATA"

    def test_validated_continues(self):
        ctx = _make_ctx(validation_state="VALIDATED")
        decision, substate, reasons, rule = _map_stage3_state(ctx)
        assert decision is None  # Continue to policy

    def test_unknown_state_fails_closed(self):
        ctx = _make_ctx(validation_state="UNKNOWN_STATE")
        decision, substate, reasons, rule = _map_stage3_state(ctx)
        assert decision == "REVIEW_REQUIRED"
        assert substate == "POLICY_EXCEPTION_REVIEW"


class TestPolicyResolution:
    def test_low_tier(self):
        ctx = _make_ctx(amount=3000.0)
        policy = _resolve_policy(ctx, auto_approve_limit=5000)
        assert policy.materiality_tier == "LOW"
        assert policy.auto_approve_eligible is True

    def test_medium_tier(self):
        ctx = _make_ctx(amount=25000.0)
        policy = _resolve_policy(ctx, auto_approve_limit=5000, manager_limit=50000)
        assert policy.materiality_tier == "MEDIUM"
        assert policy.auto_approve_eligible is False

    def test_high_tier(self):
        ctx = _make_ctx(amount=200000.0)
        policy = _resolve_policy(ctx, auto_approve_limit=5000, manager_limit=50000, director_limit=500000)
        assert policy.materiality_tier == "HIGH"

    def test_critical_tier(self):
        ctx = _make_ctx(amount=1000000.0)
        policy = _resolve_policy(ctx)
        assert policy.materiality_tier == "CRITICAL"

    def test_high_risk_vendor_disables_auto(self):
        ctx = _make_ctx(amount=3000.0, vendor_status="suspended")
        policy = _resolve_policy(ctx, auto_approve_limit=5000)
        assert policy.auto_approve_eligible is False
        assert policy.risk_tier == "HIGH"

    def test_first_payment_elevates_risk(self):
        ctx = _make_ctx(amount=3000.0, is_first_payment=True)
        policy = _resolve_policy(ctx, auto_approve_limit=5000)
        assert policy.risk_tier == "ELEVATED"
        assert policy.auto_approve_eligible is False


class TestPolicyEvaluation:
    def test_hold_stops_at_state_mapping(self):
        ctx = _make_ctx(validation_state="HOLD", reason_codes=["PRICE_VARIANCE_EXCEEDED"])
        result = evaluate_policy(ctx)
        assert result.decision == "REVIEW_REQUIRED"
        assert not result.continue_to_authority

    def test_validated_low_continues_to_authority(self):
        ctx = _make_ctx(validation_state="VALIDATED", amount=3000.0)
        result = evaluate_policy(ctx, auto_approve_limit=5000)
        assert result.continue_to_authority
        assert result.policy.auto_approve_eligible is True

    def test_validated_high_continues_to_authority(self):
        ctx = _make_ctx(validation_state="VALIDATED", amount=100000.0)
        result = evaluate_policy(ctx)
        assert result.continue_to_authority
        assert result.policy.auto_approve_eligible is False
