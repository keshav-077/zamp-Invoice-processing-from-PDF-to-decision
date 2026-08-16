"""
Tests for Stage 3: Duplicate Detection Engine
"""

import pytest
from unittest.mock import patch
from app.pipeline.stage3.validation_context import ValidationContext
from app.pipeline.stage3.duplicate_detector import detect_duplicates, _dates_within_window


def _make_ctx(**overrides) -> ValidationContext:
    defaults = dict(
        document_id="DOC-NEW",
        invoice_number="INV-2026-001",
        vendor_name="Acme Corporation",
        total_amount=10000.0,
        invoice_date="2026-08-10",
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)


class TestExactDuplicate:
    @patch("app.pipeline.stage3.duplicate_detector.repository")
    def test_exact_duplicate_found(self, mock_repo):
        mock_repo.get_prior_invoices_for_duplicate_check.return_value = [
            {
                "document_id": "DOC-OLD",
                "filename": "old.pdf",
                "status": "stage1_passed",
                "extraction_json": {
                    "invoice_number": {"value": "INV-2026-001"},
                    "vendor_name": {"value": "Acme Corporation"},
                    "total_amount": {"value": 10000.0},
                },
                "upload_timestamp": "2026-08-01",
                "stage3_status": "VALIDATED",
                "stage4_decision": "APPROVE",
            }
        ]
        ctx = _make_ctx()
        result = detect_duplicates(ctx)
        assert result.status == "FAIL"
        assert result.reason_code == "DUPLICATE_CONFIRMED"

    @patch("app.pipeline.stage3.duplicate_detector.repository")
    def test_reject_prior_does_not_block(self, mock_repo):
        mock_repo.get_prior_invoices_for_duplicate_check.return_value = [
            {
                "document_id": "DOC-OLD",
                "filename": "old.pdf",
                "status": "stage1_passed",
                "extraction_json": {
                    "invoice_number": {"value": "INV-2026-001"},
                    "vendor_name": {"value": "Acme Corporation"},
                    "total_amount": {"value": 10000.0},
                },
                "upload_timestamp": "2026-08-01",
                "stage3_status": "BLOCKED",
                "stage4_decision": "REJECT",
            }
        ]
        mock_repo.get_allocation_for_document.return_value = []
        ctx = _make_ctx()
        result = detect_duplicates(ctx)
        assert result.status == "PASS"

    @patch("app.pipeline.stage3.duplicate_detector.repository")
    def test_no_duplicates(self, mock_repo):
        mock_repo.get_prior_invoices_for_duplicate_check.return_value = []
        ctx = _make_ctx()
        result = detect_duplicates(ctx)
        assert result.status == "PASS"


class TestNearDuplicate:
    @patch("app.pipeline.stage3.duplicate_detector.repository")
    def test_same_number_different_amount(self, mock_repo):
        mock_repo.get_prior_invoices_for_duplicate_check.return_value = [
            {
                "document_id": "DOC-OLD",
                "filename": "old.pdf",
                "status": "stage1_passed",
                "extraction_json": {
                    "invoice_number": {"value": "INV-2026-001"},
                    "vendor_name": {"value": "Acme Corporation"},
                    "total_amount": {"value": 9500.0},  # Different amount
                },
                "upload_timestamp": "2026-08-01",
                "stage3_status": "",
            }
        ]
        ctx = _make_ctx()
        result = detect_duplicates(ctx)
        assert result.status == "FLAG"
        assert result.reason_code == "DUPLICATE_SUSPECTED"

    @patch("app.pipeline.stage3.duplicate_detector.repository")
    def test_self_not_counted(self, mock_repo):
        """Self-document should be skipped."""
        mock_repo.get_prior_invoices_for_duplicate_check.return_value = [
            {
                "document_id": "DOC-NEW",  # Same as current
                "filename": "new.pdf",
                "status": "stage1_passed",
                "extraction_json": {
                    "invoice_number": {"value": "INV-2026-001"},
                    "vendor_name": {"value": "Acme Corporation"},
                    "total_amount": {"value": 10000.0},
                },
                "upload_timestamp": "2026-08-10",
                "stage3_status": "",
            }
        ]
        ctx = _make_ctx()
        result = detect_duplicates(ctx)
        assert result.status == "PASS"


class TestDateWindow:
    def test_within_window(self):
        assert _dates_within_window("2026-08-10", "2026-08-12", 3) is True

    def test_outside_window(self):
        assert _dates_within_window("2026-08-10", "2026-08-20", 3) is False

    def test_invalid_date(self):
        assert _dates_within_window("bad-date", "2026-08-10", 3) is False


class TestInsufficientData:
    def test_no_invoice_data(self):
        ctx = _make_ctx(invoice_number=None, vendor_name=None)
        result = detect_duplicates(ctx)
        assert result.status == "NOT_APPLICABLE"
