"""
Tests for Stage 2 — Candidate Discovery Engine
"""
import pytest
from unittest.mock import patch
from app.pipeline.stage2.candidate_discovery import CandidateDiscovery


MOCK_POS = [
    {
        "po_number": "PO-2298",
        "vendor_id": "V001",
        "vendor_name": "Acme Corp",
        "total_amount": 7500,
        "status": "open",
        "po_type": "standard",
        "issue_date": "2026-06-01",
        "previously_invoiced": 0,
        "lines": [],
    },
    {
        "po_number": "PO-4410",
        "vendor_id": "V002",
        "vendor_name": "Global Supply",
        "total_amount": 6500,
        "status": "open",
        "po_type": "standard",
        "issue_date": "2026-05-15",
        "previously_invoiced": 0,
        "lines": [],
    },
]


class TestExactMatch:
    @patch("app.pipeline.stage2.candidate_discovery.repository")
    def test_exact_match_found(self, mock_repo):
        mock_repo.search_pos_by_number.return_value = [MOCK_POS[0]]
        mock_repo.search_pos_by_reference.return_value = []
        mock_repo.search_open_pos_by_vendor_identity.return_value = []
        mock_repo.get_po_lines.return_value = []

        cd = CandidateDiscovery()
        result = cd.discover("PO-2298", "V001", "Acme Corp", "trust")

        assert len(result) >= 1
        assert result[0]["po_number"] == "PO-2298"
        assert result[0]["_retrieval_method"] == "exact"

    @patch("app.pipeline.stage2.candidate_discovery.repository")
    def test_no_exact_match(self, mock_repo):
        mock_repo.search_pos_by_number.return_value = []
        mock_repo.search_pos_by_reference.return_value = []
        mock_repo.search_open_pos_by_vendor_identity.return_value = []
        mock_repo.get_all_open_pos.return_value = MOCK_POS
        mock_repo.get_po_lines.return_value = []

        cd = CandidateDiscovery()
        result = cd.discover("PO-UNKNOWN", None, None, "trust")
        assert isinstance(result, list)


class TestVendorSearch:
    @patch("app.pipeline.stage2.candidate_discovery.repository")
    def test_vendor_search_in_expand_mode(self, mock_repo):
        mock_repo.search_pos_by_number.return_value = []
        mock_repo.search_pos_by_reference.return_value = []
        po = dict(MOCK_POS[0])
        po["_retrieval_method"] = "vendor_search"
        po["_retrieval_confidence"] = 0.75
        mock_repo.search_open_pos_by_vendor_identity.return_value = [po]
        mock_repo.get_po_lines.return_value = []

        cd = CandidateDiscovery()
        result = cd.discover("PO-UNKNOWN", "V001", "Acme Corp", "expand", suggestion_mode=True)

        assert len(result) >= 1


class TestUnifiedPoMasterDiscovery:
    @patch("app.pipeline.stage2.candidate_discovery.repository")
    def test_vendor_identity_finds_import_mirrored_po(self, mock_repo):
        """Mirrored import POs are discovered via purchase_orders vendor search, not source_records."""
        po = dict(MOCK_POS[0])
        po["_retrieval_method"] = "import_derived"
        po["_retrieval_confidence"] = 0.85
        mock_repo.search_pos_by_number.return_value = []
        mock_repo.search_pos_by_reference.return_value = []
        mock_repo.search_open_pos_by_vendor_identity.return_value = [po]
        mock_repo.get_po_lines.return_value = []

        cd = CandidateDiscovery()
        result = cd.discover(
            po_value=None,
            vendor_id="V001",
            vendor_name="Acme Corp",
            confidence_action="trust",
            invoice_number="INV-100",
            suggestion_mode=True,
        )

        assert len(result) >= 1
        assert result[0]["po_number"] == "PO-2298"
        assert result[0]["_retrieval_method"] == "import_derived"
        mock_repo.search_source_records_by_invoice_number.assert_not_called()


class TestTrustedPOMiss:
    @patch("app.pipeline.stage2.candidate_discovery.repository")
    def test_trusted_po_miss_skips_vendor_fallback(self, mock_repo):
        mock_repo.search_pos_by_number.return_value = []
        mock_repo.search_pos_by_reference.return_value = []
        mock_repo.search_open_pos_by_vendor_identity.return_value = MOCK_POS
        mock_repo.get_po_lines.return_value = []

        cd = CandidateDiscovery()
        result = cd.discover(
            "PO-MISSING",
            "V001",
            "Acme Corp",
            "trust",
            require_exact_po=True,
        )

        mock_repo.search_open_pos_by_vendor_identity.assert_not_called()
        assert result == []


class TestNoBroadcast:
    @patch("app.pipeline.stage2.candidate_discovery.repository")
    def test_no_broadcast_without_vendor(self, mock_repo):
        mock_repo.search_pos_by_number.return_value = []
        mock_repo.search_pos_by_reference.return_value = []
        mock_repo.search_open_pos_by_vendor_identity.return_value = []
        mock_repo.get_all_open_pos.return_value = MOCK_POS

        cd = CandidateDiscovery()
        result = cd.discover("XXXXX", None, None, "expand", suggestion_mode=True)

        assert result == []
