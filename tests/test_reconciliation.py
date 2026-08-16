"""Tests for the reconciliation engine."""

import pytest

from app.models.extraction import InvoiceExtraction, FieldExtraction, ExtraCharge, LineItem
from app.pipeline.reconciliation import ReconciliationEngine


def make_field(value, confidence=0.95, status="extracted"):
    return FieldExtraction(value=value, confidence=confidence, status=status)


def test_reconciled_with_shipping_charge():
    """d11-style case: subtotal + tax + shipping = total."""
    extraction = InvoiceExtraction(
        vendor_name=make_field("Acme"),
        invoice_number=make_field("INV-1"),
        invoice_date=make_field("2020-01-28"),
        currency=make_field("USD"),
        subtotal=make_field(293.5),
        tax_amount=make_field(35.81),
        total_amount=make_field(332.80),
        extra_charges=[
            ExtraCharge(label="Shipping & Handling", amount=3.49, category="shipping", confidence=0.9),
        ],
        line_items=[],
    )
    result = ReconciliationEngine().reconcile(extraction)
    assert result.overall_status in ("reconciled", "reconciled_with_inferred_charges")


def test_inferred_residual_shipping():
    """When shipping missing, infer residual and pass with review signal."""
    extraction = InvoiceExtraction(
        vendor_name=make_field("Acme"),
        invoice_number=make_field("INV-1"),
        invoice_date=make_field("2020-01-28"),
        currency=make_field("USD"),
        subtotal=make_field(293.5),
        tax_amount=make_field(35.81),
        total_amount=make_field(332.80),
        line_items=[],
    )
    result = ReconciliationEngine().reconcile(extraction)
    assert result.overall_status in (
        "reconciled_with_inferred_charges",
        "residual_review",
    )
    assert result.inferred_charges or result.residual_amount > 0


def test_failed_reconciliation():
    extraction = InvoiceExtraction(
        vendor_name=make_field("Acme"),
        invoice_number=make_field("INV-1"),
        invoice_date=make_field("2020-01-28"),
        currency=make_field("USD"),
        subtotal=make_field(100.0),
        tax_amount=make_field(10.0),
        total_amount=make_field(200.0),
        line_items=[],
    )
    result = ReconciliationEngine().reconcile(extraction)
    assert result.overall_status in ("failed", "residual_review")
    assert result.residual_amount != 0
