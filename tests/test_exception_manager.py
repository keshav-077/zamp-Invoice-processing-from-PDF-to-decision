"""Tests for Stage 2 exception manager GRN policy."""

from app.pipeline.stage2.exception_manager import ExceptionManager


def test_grn_not_required_for_blanket_po():
    em = ExceptionManager()
    status, flags = em.determine_final_state(
        ambiguity_status="matched",
        unmatched_lines=[],
        total_lines=1,
        po_validation_flags=[],
        balance_flags=[],
        has_grn=False,
        po_type="blanket",
        grn_required_types=["standard"],
    )
    assert status == "matched"
    assert "no_grn_record" not in flags


def test_grn_required_for_standard_po():
    em = ExceptionManager()
    status, flags = em.determine_final_state(
        ambiguity_status="matched",
        unmatched_lines=[],
        total_lines=1,
        po_validation_flags=[],
        balance_flags=[],
        has_grn=False,
        po_type="standard",
        grn_required_types=["standard"],
    )
    assert status == "waiting_for_grn"
    assert "no_grn_record" in flags
