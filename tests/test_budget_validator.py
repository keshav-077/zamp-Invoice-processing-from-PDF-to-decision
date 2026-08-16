"""
Tests for Stage 3: Budget & Tolerance Validator
"""

import pytest
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.stage3.budget_validator import validate_budget


def _make_ctx(**overrides) -> ValidationContext:
    defaults = dict(
        document_id="DOC-TEST",
        total_amount=5000.0,
        po={"vendor_id": "V001", "total_amount": 20000},
        po_total=20000.0,
        po_remaining=20000.0,
        po_previously_invoiced=0.0,
        po_ref="PO-TEST:v1",
        budget_tolerance_pct=0.05,
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


class TestBudgetWithin:
    def test_well_within_budget(self):
        ctx = _make_ctx(total_amount=5000, po_remaining=20000)
        result = validate_budget(ctx)
        assert result.status == "PASS"

    def test_exactly_at_limit(self):
        ctx = _make_ctx(total_amount=20000, po_remaining=20000)
        result = validate_budget(ctx)
        assert result.status == "PASS"


class TestBudgetTolerance:
    def test_within_tolerance(self):
        """$21000 > $20000 remaining but within 5% tolerance ($21000 effective)."""
        ctx = _make_ctx(total_amount=20500, po_remaining=20000)
        result = validate_budget(ctx)
        assert result.status == "FLAG"
        assert result.reason_code == "BUDGET_TOLERANCE_USED"


class TestBudgetExceeded:
    def test_exceeds_tolerance(self):
        """$25000 >> $20000 remaining + 5% tolerance."""
        ctx = _make_ctx(total_amount=25000, po_remaining=20000)
        result = validate_budget(ctx)
        assert result.status == "FAIL"
        assert result.reason_code == "BUDGET_EXCEEDED"

    def test_cumulative_tracking(self):
        """Previously invoiced $15000, new invoice $8000 → exceeds PO $20000."""
        ctx = _make_ctx(
            total_amount=8000,
            po_remaining=5000,  # 20000 - 15000
            po_previously_invoiced=15000,
        )
        result = validate_budget(ctx)
        assert result.status == "FAIL"
        assert result.reason_code == "BUDGET_EXCEEDED"


class TestNoPO:
    def test_no_po_not_applicable(self):
        ctx = _make_ctx(po=None)
        result = validate_budget(ctx)
        assert result.status == "NOT_APPLICABLE"
