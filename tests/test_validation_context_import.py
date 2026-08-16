"""Validation context — import-derived PO tax policy."""

from unittest.mock import patch

from app.models.extraction import FieldExtraction, InvoiceExtraction
from app.models.match import MatchPackage, POCandidate, ScoreBreakdown
from app.pipeline.stage3.validation_context import build_context


def _extraction() -> InvoiceExtraction:
    return InvoiceExtraction(
        vendor_name=FieldExtraction(value="Acme", confidence=0.9),
        invoice_number=FieldExtraction(value="INV-1", confidence=0.9),
        total_amount=FieldExtraction(value=118.0, confidence=0.9),
        subtotal=FieldExtraction(value=100.0, confidence=0.9),
        tax_amount=FieldExtraction(value=18.0, confidence=0.9),
    )


def _match_package() -> MatchPackage:
    return MatchPackage(
        invoice_id="doc-1",
        match_status="high_confidence_match",
        matched_pos=[
            POCandidate(
                po_number="IMP-1",
                vendor_id="V1",
                vendor_name="Acme",
                score=ScoreBreakdown(total=50),
            )
        ],
    )


@patch("app.pipeline.stage3.validation_context.repository")
def test_import_derived_po_uses_consistency_tax(mock_repo):
    mock_repo.get_po.return_value = {
        "po_number": "IMP-1",
        "vendor_id": "V1",
        "total_amount": 118.0,
        "previously_invoiced": 0,
        "status": "open",
        "po_type": "blanket",
        "metadata": {"import_derived": True},
        "lines": [],
    }
    mock_repo.get_vendor_by_id.return_value = {
        "vendor_id": "V1",
        "name": "Acme",
        "status": "active",
    }
    mock_repo.get_grn_for_po.return_value = []

    ctx = build_context("doc-1", _extraction(), _match_package())
    # consistency_only mirrors invoice rate — 18% on subtotal
    assert abs(ctx.expected_tax_rate - 0.18) < 0.001
