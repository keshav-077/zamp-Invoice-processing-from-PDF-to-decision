"""
InvoiceFlow AI — Arithmetic Validator Tests

Tests all arithmetic check scenarios including:
- Correct totals
- Mismatched totals
- Missing fields (skip behavior)
- Line item validation
- Edge cases (zero, negative, rounding)
"""

import pytest
from app.models.extraction import InvoiceExtraction, FieldExtraction, LineItem
from app.pipeline.arithmetic import ArithmeticValidator


def make_field(value, confidence=0.95, status="extracted"):
    return FieldExtraction(value=value, confidence=confidence, status=status)


def make_extraction(
    subtotal=None, tax=None, total=None, line_items=None
):
    """Helper to create an InvoiceExtraction with specified financial values."""
    return InvoiceExtraction(
        vendor_name=make_field("Test Corp"),
        invoice_number=make_field("INV-001"),
        invoice_date=make_field("2026-01-15"),
        due_date=make_field(None, 0, "not_found"),
        po_reference=make_field(None, 0, "not_found"),
        currency=make_field("USD"),
        subtotal=make_field(subtotal) if subtotal is not None else make_field(None, 0, "not_found"),
        tax_amount=make_field(tax) if tax is not None else make_field(None, 0, "not_found"),
        total_amount=make_field(total) if total is not None else make_field(None, 0, "not_found"),
        line_items=line_items or [],
    )


class TestSubtotalPlusTax:
    """Tests for subtotal + tax = total check."""

    def test_correct_totals(self):
        ext = make_extraction(subtotal=1000, tax=80, total=1080)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "subtotal_plus_tax_equals_total")
        assert check.status == "pass"

    def test_incorrect_totals(self):
        ext = make_extraction(subtotal=1000, tax=80, total=1200)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "subtotal_plus_tax_equals_total")
        assert check.status == "fail"

    def test_missing_subtotal(self):
        ext = make_extraction(tax=80, total=1080)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "subtotal_plus_tax_equals_total")
        assert check.status == "skipped"

    def test_missing_tax(self):
        ext = make_extraction(subtotal=1000, total=1080)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "subtotal_plus_tax_equals_total")
        assert check.status == "skipped"

    def test_rounding_tolerance(self):
        """Values within 1-cent tolerance should pass."""
        ext = make_extraction(subtotal=1000, tax=80.005, total=1080.01)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "subtotal_plus_tax_equals_total")
        assert check.status == "pass"


class TestLineItemAmounts:
    """Tests for line item quantity × unit_price = amount."""

    def test_correct_line_items(self):
        items = [
            LineItem(description="Widget", quantity=5, unit_price=20, amount=100, confidence=0.9),
            LineItem(description="Gadget", quantity=2, unit_price=50, amount=100, confidence=0.9),
        ]
        ext = make_extraction(subtotal=200, tax=16, total=216, line_items=items)
        result = ArithmeticValidator().validate(ext)
        line_checks = [c for c in result.checks if "line_item" in c.check_name]
        assert all(c.status == "pass" for c in line_checks)

    def test_incorrect_line_item(self):
        items = [
            LineItem(description="Widget", quantity=5, unit_price=20, amount=150, confidence=0.9),
        ]
        ext = make_extraction(subtotal=150, tax=12, total=162, line_items=items)
        result = ArithmeticValidator().validate(ext)
        line_checks = [c for c in result.checks if "line_item" in c.check_name]
        assert any(c.status == "fail" for c in line_checks)

    def test_missing_quantity(self):
        items = [
            LineItem(description="Service", quantity=None, unit_price=100, amount=100, confidence=0.9),
        ]
        ext = make_extraction(subtotal=100, tax=8, total=108, line_items=items)
        result = ArithmeticValidator().validate(ext)
        # Only the per-line qty×price check should be skipped (not the sum check)
        per_line_checks = [c for c in result.checks if c.check_name.startswith("line_item_")]
        assert all(c.status == "skipped" for c in per_line_checks)


class TestLineItemsSum:
    """Tests for sum(line items) ≈ subtotal."""

    def test_correct_sum(self):
        items = [
            LineItem(description="A", quantity=1, unit_price=100, amount=100, confidence=0.9),
            LineItem(description="B", quantity=1, unit_price=200, amount=200, confidence=0.9),
        ]
        ext = make_extraction(subtotal=300, tax=24, total=324, line_items=items)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "line_items_sum_equals_subtotal")
        assert check.status == "pass"

    def test_incorrect_sum(self):
        items = [
            LineItem(description="A", quantity=1, unit_price=100, amount=100, confidence=0.9),
        ]
        ext = make_extraction(subtotal=500, tax=40, total=540, line_items=items)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "line_items_sum_equals_subtotal")
        assert check.status == "fail"


class TestSanityChecks:
    """Tests for positive total and tax ≤ total."""

    def test_positive_total(self):
        ext = make_extraction(total=100)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "positive_total")
        assert check.status == "pass"

    def test_zero_total(self):
        ext = make_extraction(total=0)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "positive_total")
        assert check.status == "fail"

    def test_tax_within_total(self):
        ext = make_extraction(tax=50, total=500)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "tax_not_exceeds_total")
        assert check.status == "pass"

    def test_tax_exceeds_total(self):
        ext = make_extraction(tax=600, total=500)
        result = ArithmeticValidator().validate(ext)
        check = next(c for c in result.checks if c.check_name == "tax_not_exceeds_total")
        assert check.status == "fail"


class TestOverallStatus:
    """Tests for aggregate overall status."""

    def test_all_pass(self):
        ext = make_extraction(subtotal=100, tax=10, total=110)
        result = ArithmeticValidator().validate(ext)
        assert result.overall_status in ("pass", "partial")  # partial if some skipped

    def test_any_fail(self):
        ext = make_extraction(subtotal=100, tax=10, total=200)
        result = ArithmeticValidator().validate(ext)
        assert result.overall_status == "fail"
