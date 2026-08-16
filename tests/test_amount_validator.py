"""
Tests for Stage 3: Amount & Price Variance Validator
"""

import pytest
from app.models.validation import ValidationCheck
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.stage3.amount_validator import validate_amount


def _make_ctx(**overrides) -> ValidationContext:
    """Build a ValidationContext with defaults + overrides."""
    defaults = dict(
        document_id="DOC-TEST",
        total_amount=10000.00,
        po={"vendor_id": "V001", "total_amount": 10000},
        po_total=10000.00,
        po_remaining=10000.00,
        po_previously_invoiced=0.0,
        po_status="open",
        po_ref="PO-TEST:v1",
        price_tolerance_pct=0.02,
        qty_tolerance_pct=0.05,
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


class TestPriceVariance:
    def test_within_tolerance(self):
        ctx = _make_ctx(
            invoice_lines=[{"description": "Widget", "quantity": 10, "unit_price": 101.0, "amount": 1010}],
            po_lines=[{"line_number": 1, "description": "Widget", "quantity": 10, "unit_price": 100.0, "amount": 1000}],
            line_mappings=[{"invoice_line": 1, "po_line": 1, "match_type": "exact", "similarity_score": 1.0}],
        )
        result = validate_amount(ctx)
        assert result.status == "PASS"

    def test_price_exceeded(self):
        ctx = _make_ctx(
            invoice_lines=[{"description": "Widget", "quantity": 10, "unit_price": 110.0, "amount": 1100}],
            po_lines=[{"line_number": 1, "description": "Widget", "quantity": 10, "unit_price": 100.0, "amount": 1000}],
            line_mappings=[{"invoice_line": 1, "po_line": 1, "match_type": "exact", "similarity_score": 1.0}],
        )
        result = validate_amount(ctx)
        assert result.status == "FAIL"
        assert result.reason_code == "PRICE_VARIANCE_EXCEEDED"

    def test_quantity_over_invoiced(self):
        ctx = _make_ctx(
            invoice_lines=[{"description": "Widget", "quantity": 12, "unit_price": 100.0, "amount": 1200}],
            po_lines=[{"line_number": 1, "description": "Widget", "quantity": 10, "unit_price": 100.0, "amount": 1000}],
            line_mappings=[{"invoice_line": 1, "po_line": 1, "match_type": "exact", "similarity_score": 1.0}],
        )
        result = validate_amount(ctx)
        # Qty over-invoiced creates FLAG
        assert result.status in ("FLAG", "FAIL")


class TestPOBalance:
    def test_within_balance(self):
        ctx = _make_ctx(total_amount=5000.0, po_remaining=10000.0, po_total=10000.0)
        # No line mappings → no line checks. Header variance: 5000 vs 10000 = 50% → FLAG.
        # To test balance only, set po_total equal to total_amount
        ctx.po_total = 5000.0
        result = validate_amount(ctx)
        assert result.status == "PASS"

    def test_exceeds_balance(self):
        ctx = _make_ctx(total_amount=15000.0, po_remaining=10000.0)
        result = validate_amount(ctx)
        assert result.status in ("FLAG", "FAIL")
        assert any("exceeds" in e.lower() for e in result.evidence)


class TestNoPO:
    def test_no_po_not_applicable(self):
        ctx = _make_ctx(po=None)
        result = validate_amount(ctx)
        assert result.status == "NOT_APPLICABLE"
        assert result.reason_code == "NO_PO_CONTEXT"


class TestEvidence:
    def test_evidence_populated(self):
        ctx = _make_ctx(
            invoice_lines=[{"description": "Widget", "quantity": 10, "unit_price": 150.0, "amount": 1500}],
            po_lines=[{"line_number": 1, "description": "Widget", "quantity": 10, "unit_price": 100.0, "amount": 1000}],
            line_mappings=[{"invoice_line": 1, "po_line": 1, "match_type": "exact", "similarity_score": 1.0}],
        )
        result = validate_amount(ctx)
        assert len(result.evidence) > 0
        assert len(result.calculation) > 0
