"""
Tests for Stage 3: Tax Validator
"""

import pytest
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.stage3.tax_validator import validate_tax


def _make_ctx(**overrides) -> ValidationContext:
    defaults = dict(
        document_id="DOC-TEST",
        expected_tax_rate=0.18,
        tax_tolerance_pct=0.01,
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


class TestTaxRate:
    def test_correct_rate(self):
        ctx = _make_ctx(subtotal=100000, tax_amount=18000, total_amount=118000)
        result = validate_tax(ctx)
        assert result.status == "PASS"

    def test_tax_variance_exceeded(self):
        ctx = _make_ctx(subtotal=100000, tax_amount=20000, total_amount=120000)
        result = validate_tax(ctx)
        assert result.status == "FAIL"
        assert result.reason_code == "TAX_VARIANCE"

    def test_tax_within_tolerance(self):
        # 18% of 100000 = 18000 → 18100 is 0.56% variance, within 1%
        ctx = _make_ctx(subtotal=100000, tax_amount=18100, total_amount=118100)
        result = validate_tax(ctx)
        assert result.status == "PASS"


class TestZeroTax:
    def test_zero_tax_invoice(self):
        ctx = _make_ctx(subtotal=50000, tax_amount=0, total_amount=50000)
        result = validate_tax(ctx)
        assert result.status == "PASS"

    def test_no_tax_data(self):
        ctx = _make_ctx(subtotal=None, tax_amount=None)
        result = validate_tax(ctx)
        assert result.status == "NOT_APPLICABLE"


class TestEdgeCases:
    def test_tax_no_subtotal(self):
        ctx = _make_ctx(subtotal=None, tax_amount=5000, total_amount=55000)
        result = validate_tax(ctx)
        assert result.status == "FLAG"
        assert result.reason_code == "TAX_BASE_MISSING"
