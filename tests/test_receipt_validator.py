"""
Tests for Stage 3: Receipt / 2-Way / 3-Way Match Validator
"""

import pytest
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.stage3.receipt_validator import validate_receipt


def _make_ctx(**overrides) -> ValidationContext:
    defaults = dict(
        document_id="DOC-TEST",
        total_amount=10000.0,
        matched_po_number="PO-TEST",
        po={"vendor_id": "V001", "total_amount": 10000},
        po_type="standard",
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


class TestThreeWayMatch:
    def test_full_receipt_pass(self):
        """Goods PO with full GRN → PASS."""
        ctx = _make_ctx(
            has_grn=True,
            grn_records=[{"grn_id": "GRN-1", "received_amount": 10000}],
            total_received_amount=10000.0,
        )
        result = validate_receipt(ctx)
        assert result.status == "PASS"

    def test_partial_receipt_flag(self):
        """Goods PO with partial GRN → FLAG."""
        ctx = _make_ctx(
            has_grn=True,
            grn_records=[{"grn_id": "GRN-1", "received_amount": 6000}],
            total_received_amount=6000.0,
        )
        result = validate_receipt(ctx)
        assert result.status == "FLAG"
        assert result.reason_code == "PARTIAL_RECEIPT"

    def test_missing_grn_unavailable(self):
        """Goods PO with no GRN → UNAVAILABLE."""
        ctx = _make_ctx(has_grn=False, grn_records=[])
        result = validate_receipt(ctx)
        assert result.status == "UNAVAILABLE"
        assert result.reason_code == "GRN_MISSING"


class TestTwoWayMatch:
    def test_blanket_po_no_grn_needed(self):
        """Blanket/service PO → 2-way match, no GRN required."""
        ctx = _make_ctx(po_type="blanket", has_grn=False)
        result = validate_receipt(ctx)
        assert result.status == "PASS"
        assert "2-way match" in result.evidence[0]


class TestNoPO:
    def test_no_po_not_applicable(self):
        ctx = _make_ctx(po=None)
        result = validate_receipt(ctx)
        assert result.status == "NOT_APPLICABLE"


class TestEdgeCases:
    def test_low_receipt_coverage(self):
        """Very low receipt coverage → FLAG with HIGH severity."""
        ctx = _make_ctx(
            has_grn=True,
            grn_records=[{"grn_id": "GRN-1", "received_amount": 2000}],
            total_received_amount=2000.0,
        )
        result = validate_receipt(ctx)
        assert result.status == "FLAG"
        assert result.severity == "HIGH"
