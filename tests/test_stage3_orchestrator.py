"""
Tests for Stage 3: Validation Orchestrator

Integration-level tests for the complete Stage 3 pipeline.
"""

import pytest
from unittest.mock import patch, MagicMock
from app.models.extraction import InvoiceExtraction, FieldExtraction, LineItem
from app.models.match import MatchPackage, POCandidate, ScoreBreakdown, LineMapping
from app.pipeline.stage3.orchestrator import Stage3Orchestrator
from app.pipeline.stage3.contract_gate import validate_contract


# ═══════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════

def _make_extraction(**overrides) -> InvoiceExtraction:
    defaults = dict(
        vendor_name=FieldExtraction(value="Acme Corporation", confidence=0.98, status="extracted"),
        invoice_number=FieldExtraction(value="INV-2026-001", confidence=0.99, status="extracted"),
        invoice_date=FieldExtraction(value="2026-08-10", confidence=0.95, status="extracted"),
        po_reference=FieldExtraction(value="PO-001", confidence=0.97, status="extracted"),
        currency=FieldExtraction(value="USD", confidence=0.99, status="extracted"),
        subtotal=FieldExtraction(value=10000, confidence=0.98, status="extracted"),
        tax_amount=FieldExtraction(value=800, confidence=0.97, status="extracted"),
        total_amount=FieldExtraction(value=10800, confidence=0.99, status="extracted"),
        line_items=[
            LineItem(description="Widget A", quantity=100, unit_price=50, amount=5000, confidence=0.95),
            LineItem(description="Widget B", quantity=50, unit_price=100, amount=5000, confidence=0.95),
        ],
    )
    defaults.update(overrides)
    return InvoiceExtraction(**defaults)


def _make_match_package(
    status="matched", po_number="PO-001", vendor_id="V001", score_total=90,
) -> MatchPackage:
    return MatchPackage(
        invoice_id="DOC-TEST",
        match_status=status,
        matched_pos=[
            POCandidate(
                po_number=po_number,
                vendor_id=vendor_id,
                vendor_name="Acme Corporation",
                score=ScoreBreakdown(
                    po_match=40, vendor_match=20, line_match=18,
                    amount_match=8, date_match=4,
                ),
                line_mappings=[
                    LineMapping(
                        invoice_line=1, po_number=po_number, po_line=1,
                        match_type="exact", similarity_score=0.95,
                    ),
                    LineMapping(
                        invoice_line=2, po_number=po_number, po_line=2,
                        match_type="semantic", similarity_score=0.88,
                    ),
                ],
                po_status="open",
                remaining_balance=15000,
            )
        ],
        resolved_invoice_vendor_id=vendor_id,
        match_provenance="authoritative_po",
    )


# ═══════════════════════════════════════════════════════════
# Contract Gate Tests
# ═══════════════════════════════════════════════════════════

class TestContractGate:
    def test_matched_full_validation(self):
        mp = _make_match_package(status="matched")
        result = validate_contract("DOC-TEST", mp)
        assert result.is_valid
        assert result.validation_mode == "full"
        assert len(result.engines_to_run) == 7

    def test_non_po_limited_validation(self):
        mp = _make_match_package(status="non_po_workflow")
        result = validate_contract("DOC-TEST", mp)
        assert result.is_valid
        assert result.validation_mode == "limited"
        assert "duplicate_detection" in result.engines_to_run
        assert "amount_variance" not in result.engines_to_run

    def test_unmatched_no_validation(self):
        mp = _make_match_package(status="unmatched")
        result = validate_contract("DOC-TEST", mp)
        assert result.validation_mode == "none"

    def test_waiting_for_po_no_validation(self):
        mp = _make_match_package(status="waiting_for_po")
        result = validate_contract("DOC-TEST", mp)
        assert result.validation_mode == "none"

    def test_missing_invoice_id(self):
        mp = _make_match_package()
        result = validate_contract("", mp)
        assert not result.is_valid


# ═══════════════════════════════════════════════════════════
# Full Pipeline Tests (mocked DB)
# ═══════════════════════════════════════════════════════════

class TestFullPipeline:
    @patch("app.pipeline.stage3.validation_context.repository")
    @patch("app.pipeline.stage3.duplicate_detector.repository")
    @patch("app.pipeline.stage3.orchestrator.repository")
    def test_happy_path_validated(self, mock_orch_repo, mock_dup_repo, mock_ctx_repo):
        """All checks pass → VALIDATED."""
        mock_ctx_repo.get_po.return_value = {
            "po_number": "PO-001", "vendor_id": "V001", "vendor_name": "Acme",
            "total_amount": 10800, "currency": "USD", "status": "open",
            "po_type": "standard", "previously_invoiced": 0,
            "lines": [
                {"line_number": 1, "description": "Widget A", "quantity": 100, "unit_price": 50, "amount": 5000},
                {"line_number": 2, "description": "Widget B", "quantity": 50, "unit_price": 100, "amount": 5000},
            ],
        }
        mock_ctx_repo.get_vendor_by_id.return_value = {
            "vendor_id": "V001", "name": "Acme Corporation", "status": "active",
        }
        mock_ctx_repo.get_grn_for_po.return_value = [
            {"grn_id": "GRN-1", "po_number": "PO-001", "received_amount": 10800},
        ]
        mock_dup_repo.get_prior_invoices_for_duplicate_check.return_value = []

        orchestrator = Stage3Orchestrator()
        report = orchestrator.validate(
            "DOC-TEST", _make_extraction(), _make_match_package()
        )

        assert report.processing_state == "COMPLETED"
        assert report.overall_state == "VALIDATED"
        assert len(report.checks) == 8  # includes extraction_completeness
        assert report.next_action == "STAGE4_DECISION"

    @patch("app.pipeline.stage3.validation_context.repository")
    @patch("app.pipeline.stage3.duplicate_detector.repository")
    @patch("app.pipeline.stage3.orchestrator.repository")
    def test_non_po_limited(self, mock_orch_repo, mock_dup_repo, mock_ctx_repo):
        """Non-PO workflow → limited validation (3 engines)."""
        mock_ctx_repo.get_po.return_value = None
        mock_ctx_repo.get_vendor_by_id.return_value = None
        mock_ctx_repo.get_grn_for_po.return_value = []
        mock_dup_repo.get_prior_invoices_for_duplicate_check.return_value = []

        mp = _make_match_package(status="non_po_workflow")
        mp.matched_pos = []

        orchestrator = Stage3Orchestrator()
        report = orchestrator.validate("DOC-TEST", _make_extraction(), mp)

        assert report.processing_state == "COMPLETED"
        assert len(report.checks) == 4  # duplicate, vendor, fraud, extraction_completeness

    @patch("app.pipeline.stage3.validation_context.repository")
    @patch("app.pipeline.stage3.duplicate_detector.repository")
    @patch("app.pipeline.stage3.orchestrator.repository")
    def test_unmatched_incomplete(self, mock_orch_repo, mock_dup_repo, mock_ctx_repo):
        """Unmatched → VALIDATION_INCOMPLETE (no engines run)."""
        mp = _make_match_package(status="unmatched")
        mp.matched_pos = []

        orchestrator = Stage3Orchestrator()
        report = orchestrator.validate("DOC-TEST", _make_extraction(), mp)

        assert report.overall_state == "VALIDATION_INCOMPLETE"
        assert len(report.checks) == 0
