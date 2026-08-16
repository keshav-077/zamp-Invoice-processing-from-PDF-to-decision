"""
Tests for Stage 2 — Confidence Gate, PO Presence, Ambiguity Detector, Exception Manager
"""
import pytest
from app.pipeline.stage2.confidence_gate import evaluate_confidence
from app.pipeline.stage2.po_presence import check_po_presence
from app.pipeline.stage2.ambiguity_detector import detect_ambiguity
from app.pipeline.stage2.exception_manager import ExceptionManager
from app.models.match import POCandidate, ScoreBreakdown


class TestConfidenceGate:
    def test_high_confidence_trust(self):
        assert evaluate_confidence("PO-123", 0.95, "extracted") == "trust"

    def test_medium_confidence_validate(self):
        assert evaluate_confidence("PO-123", 0.80, "extracted") == "validate"

    def test_low_confidence_expand(self):
        assert evaluate_confidence("PO-123", 0.50, "extracted") == "expand"

    def test_no_po_expand(self):
        assert evaluate_confidence(None, 0.0, "not_found") == "expand"

    def test_uncertain_status_validate(self):
        assert evaluate_confidence("PO-123", 0.95, "uncertain") == "validate"


class TestPOPresence:
    def test_po_present(self):
        assert check_po_presence("PO-2298", "extracted") == "po_invoice"

    def test_no_po(self):
        assert check_po_presence(None, "not_found") == "non_po"

    def test_na_value(self):
        assert check_po_presence("N/A", "extracted") == "non_po"

    def test_none_string(self):
        assert check_po_presence("none", "extracted") == "non_po"

    def test_empty_string(self):
        assert check_po_presence("", "extracted") == "non_po"


class TestAmbiguityDetector:
    def _make_candidate(self, po_number: str, total_score: float) -> POCandidate:
        """Helper to create a candidate with a given total score."""
        # Distribute score into po_match primarily
        return POCandidate(
            po_number=po_number,
            vendor_id="V001",
            score=ScoreBreakdown(
                po_match=min(total_score, 40),
                vendor_match=min(max(total_score - 40, 0), 20),
                line_match=min(max(total_score - 60, 0), 20),
                amount_match=min(max(total_score - 80, 0), 10),
                date_match=min(max(total_score - 90, 0), 5),
            ),
        )

    def test_single_high_score_matched(self):
        candidates = [self._make_candidate("PO-1", 96)]
        status, selected = detect_ambiguity(candidates)
        assert status == "matched"
        assert len(selected) == 1

    def test_single_medium_score(self):
        candidates = [self._make_candidate("PO-1", 87)]
        status, selected = detect_ambiguity(candidates)
        assert status == "high_confidence_match"

    def test_single_low_score_unmatched(self):
        candidates = [self._make_candidate("PO-1", 50)]
        status, selected = detect_ambiguity(candidates)
        assert status == "unmatched"

    def test_ambiguous_small_gap(self):
        candidates = [
            self._make_candidate("PO-1", 91),
            self._make_candidate("PO-2", 89),
        ]
        status, selected = detect_ambiguity(candidates)
        assert status == "ambiguous_match"
        assert len(selected) == 2

    def test_clear_winner_large_gap(self):
        candidates = [
            self._make_candidate("PO-1", 95),
            self._make_candidate("PO-2", 60),
        ]
        status, selected = detect_ambiguity(candidates)
        assert status in ("matched", "high_confidence_match")
        assert len(selected) == 1

    def test_no_candidates(self):
        status, selected = detect_ambiguity([])
        assert status == "unmatched"
        assert selected == []


class TestExceptionManager:
    def test_cancelled_po(self):
        em = ExceptionManager()
        status, flags = em.determine_final_state(
            ambiguity_status="matched",
            unmatched_lines=[],
            total_lines=3,
            po_validation_flags=["cancelled_po"],
            balance_flags=[],
            has_grn=True,
        )
        assert status == "closed_po_review"

    def test_no_grn(self):
        em = ExceptionManager()
        status, flags = em.determine_final_state(
            ambiguity_status="matched",
            unmatched_lines=[],
            total_lines=3,
            po_validation_flags=[],
            balance_flags=[],
            has_grn=False,
        )
        assert status == "waiting_for_grn"

    def test_partial_match(self):
        em = ExceptionManager()
        status, flags = em.determine_final_state(
            ambiguity_status="matched",
            unmatched_lines=[3],
            total_lines=3,
            po_validation_flags=[],
            balance_flags=[],
            has_grn=True,
        )
        assert status == "partial_match"

    def test_clean_match(self):
        em = ExceptionManager()
        status, flags = em.determine_final_state(
            ambiguity_status="matched",
            unmatched_lines=[],
            total_lines=3,
            po_validation_flags=[],
            balance_flags=[],
            has_grn=True,
        )
        assert status == "matched"

    def test_overbilling_flag(self):
        em = ExceptionManager()
        status, flags = em.determine_final_state(
            ambiguity_status="high_confidence_match",
            unmatched_lines=[],
            total_lines=3,
            po_validation_flags=[],
            balance_flags=["potential_overbilling"],
            has_grn=True,
        )
        assert "overbilling_warning" in flags
