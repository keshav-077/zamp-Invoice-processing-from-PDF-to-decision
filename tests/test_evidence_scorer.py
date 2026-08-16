"""
Tests for Stage 2 — Evidence-Based Scoring Engine
"""
import pytest
from app.pipeline.stage2.evidence_scorer import EvidenceScorer
from app.models.match import LineMapping


class TestPOMatchScoring:
    def test_exact_match_full_score(self):
        scorer = EvidenceScorer()
        breakdown, evidence = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.90,
            line_mappings=[
                LineMapping(invoice_line=1, po_number="PO-1", po_line=1,
                            match_type="exact", similarity_score=0.9, detail="SKU match"),
            ],
            invoice_total=7500,
            po_total=7500,
            invoice_date="2026-08-01",
            po_issue_date="2026-06-01",
        )
        assert breakdown.po_match == 40.0  # exact = max
        assert breakdown.vendor_match > 0
        assert breakdown.total >= 80

    def test_fuzzy_match_low_score(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="fuzzy",
            retrieval_confidence=0.4,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.5,
            line_mappings=[],
            invoice_total=1000,
            po_total=7500,
            invoice_date=None,
            po_issue_date="2026-06-01",
        )
        assert breakdown.po_match < 10
        assert breakdown.total < 30


class TestAmountScoring:
    def test_perfect_amount_alignment(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.0,
            line_mappings=[],
            invoice_total=7500,
            po_total=7500,
            invoice_date=None,
            po_issue_date="",
        )
        assert breakdown.amount_match == 10.0  # max

    def test_partial_invoice_within_remaining_gets_full_score(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.0,
            line_mappings=[],
            invoice_total=1000,
            po_total=10000,
            invoice_date=None,
            po_issue_date="",
            po_remaining=10000,
            balance_ok=True,
        )
        assert breakdown.amount_match == 10.0

    def test_overbilling_penalized(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.0,
            line_mappings=[],
            invoice_total=12000,
            po_total=10000,
            invoice_date=None,
            po_issue_date="",
            po_remaining=10000,
            balance_ok=False,
        )
        assert breakdown.amount_match <= 5


class TestDateScoring:
    def test_close_dates(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.0,
            line_mappings=[],
            invoice_total=None,
            po_total=0,
            invoice_date="2026-07-15",
            po_issue_date="2026-06-01",
        )
        assert breakdown.date_match >= 3.5  # within 90 days

    def test_missing_date(self):
        scorer = EvidenceScorer()
        breakdown, _ = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.0,
            line_mappings=[],
            invoice_total=None,
            po_total=0,
            invoice_date=None,
            po_issue_date="2026-06-01",
        )
        assert breakdown.date_match == 0.0


class TestLineScoring:
    def test_all_lines_matched(self):
        scorer = EvidenceScorer()
        mappings = [
            LineMapping(invoice_line=1, po_number="PO-1", po_line=1,
                        match_type="exact", similarity_score=0.9, detail=""),
            LineMapping(invoice_line=2, po_number="PO-1", po_line=2,
                        match_type="semantic", similarity_score=0.7, detail=""),
        ]
        breakdown, _ = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.0,
            line_mappings=mappings,
            invoice_total=None,
            po_total=0,
            invoice_date=None,
            po_issue_date="",
        )
        assert breakdown.line_match >= 15  # Good line match

    def test_no_lines_matched(self):
        scorer = EvidenceScorer()
        mappings = [
            LineMapping(invoice_line=1, po_number="PO-1", po_line=0,
                        match_type="unmatched", similarity_score=0.0, detail=""),
        ]
        breakdown, _ = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.0,
            line_mappings=mappings,
            invoice_total=None,
            po_total=0,
            invoice_date=None,
            po_issue_date="",
        )
        assert breakdown.line_match == 0.0


class TestEvidenceStrings:
    def test_evidence_contains_details(self):
        scorer = EvidenceScorer()
        _, evidence = scorer.score(
            retrieval_method="exact",
            retrieval_confidence=1.0,
            resolved_vendor_id="V1",
            candidate_vendor_id="V1",
            vendor_confidence=0.9,
            line_mappings=[
                LineMapping(invoice_line=1, po_number="PO-1", po_line=1,
                            match_type="exact", similarity_score=0.9, detail=""),
            ],
            invoice_total=7500,
            po_total=7500,
            invoice_date="2026-08-01",
            po_issue_date="2026-06-01",
        )
        assert len(evidence) >= 3
        assert any("PO match" in e for e in evidence)
        assert any("Vendor" in e for e in evidence)
