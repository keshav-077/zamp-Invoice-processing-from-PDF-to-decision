"""
Tests for Stage 4: Contract & Freshness Gate
"""

import pytest
from datetime import datetime, timezone, timedelta
from app.pipeline.stage4.decision_context import DecisionContext
from app.pipeline.stage4.contract_gate import validate_decision_contract


def _make_ctx(**overrides) -> DecisionContext:
    defaults = dict(
        decision_request_id="DR-TEST",
        invoice_id="DOC-TEST",
        validation_run_id="VR-TEST",
        validation_state="VALIDATED",
        validation_processing_state="COMPLETED",
        validated_at=datetime.now(timezone.utc).isoformat(),
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


class TestSchemaValidation:
    def test_valid_contract(self):
        ctx = _make_ctx()
        result = validate_decision_contract(ctx)
        assert result.is_valid

    def test_missing_invoice_id(self):
        ctx = _make_ctx(invoice_id="")
        result = validate_decision_contract(ctx)
        assert not result.is_valid
        assert result.reason == "MISSING_INVOICE_ID"

    def test_missing_validation_run_id(self):
        ctx = _make_ctx(validation_run_id="")
        result = validate_decision_contract(ctx)
        assert not result.is_valid
        assert result.reason == "MISSING_VALIDATION_RUN_ID"

    def test_missing_validation_state(self):
        ctx = _make_ctx(validation_state="")
        result = validate_decision_contract(ctx)
        assert not result.is_valid
        assert result.reason == "MISSING_VALIDATION_STATE"


class TestProcessingState:
    def test_not_completed(self):
        ctx = _make_ctx(validation_processing_state="FAILED")
        result = validate_decision_contract(ctx)
        assert not result.is_valid
        assert result.decision == "WAITING_FOR_VALIDATION"
        assert result.reason == "STAGE3_NOT_COMPLETED"


class TestFreshness:
    def test_fresh_validation(self):
        ctx = _make_ctx(validated_at=datetime.now(timezone.utc).isoformat())
        result = validate_decision_contract(ctx, freshness_hours=24)
        assert result.is_valid

    def test_stale_validation(self):
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        ctx = _make_ctx(validated_at=stale_time)
        result = validate_decision_contract(ctx, freshness_hours=24)
        assert not result.is_valid
        assert result.substate == "REVALIDATION_REQUIRED"
        assert result.reason == "STALE_VALIDATION"

    def test_no_timestamp_passes(self):
        """Missing timestamp should not fail (graceful)."""
        ctx = _make_ctx(validated_at="")
        result = validate_decision_contract(ctx)
        assert result.is_valid
