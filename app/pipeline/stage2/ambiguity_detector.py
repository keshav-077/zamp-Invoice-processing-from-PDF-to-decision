"""
InvoiceFlow AI — Stage 2: Ambiguity Detection Engine

Evidence-gated auto-match for no-PO invoices + gap rules for multi-candidate cases.
Includes unique vendor+amount policy (Spec Section 10).
"""

import logging

from app.models.match import POCandidate
from app.pipeline.policy_loader import load_matching_policy

logger = logging.getLogger(__name__)


def _line_coverage(candidate: POCandidate) -> float:
    if not candidate.line_mappings:
        return 0.0
    matched = sum(1 for m in candidate.line_mappings if m.match_type != "unmatched")
    return matched / len(candidate.line_mappings)


def _amount_fits_remaining(
    candidate: POCandidate,
    invoice_total: float | None,
    max_tolerance_pct: float,
    allow_partial_usage: bool = False,
) -> bool:
    if invoice_total is None or candidate.remaining_balance <= 0:
        return False
    remaining = candidate.remaining_balance
    if invoice_total > remaining * (1 + max_tolerance_pct):
        return False
    if allow_partial_usage:
        return invoice_total > 0
    lower = remaining * (1 - max_tolerance_pct)
    return lower <= invoice_total <= remaining * (1 + max_tolerance_pct)


def _suggestion_review_status(po_presence: str) -> str:
    """Status when suggestions exist but auto-match gates failed."""
    return "suggested_po_match" if po_presence == "non_po" else "waiting_for_po"


def _passes_unique_vendor_amount_gate(
    top: POCandidate,
    all_candidates: list[POCandidate],
    invoice_total: float | None,
    invoice_currency: str | None,
    po_currency: str | None,
    policy: dict,
) -> bool:
    """Unique vendor+amount match without line items (Spec Section 10)."""
    gate = policy.get("unique_vendor_amount_match", {})
    if not gate.get("enabled", True):
        return False
    allow_partial = gate.get("allow_partial_usage", False)

    viable = [
        c
        for c in all_candidates
        if c.score.vendor_match >= gate.get("min_vendor_match", 15)
        and c.score.amount_match >= gate.get("min_amount_match", 8)
        and "potential_overbilling" not in c.flags
        and _amount_fits_remaining(
            c,
            invoice_total,
            float(gate.get("max_tolerance_pct", 0.02)),
            allow_partial_usage=allow_partial,
        )
    ]
    if gate.get("require_single_candidate", True) and len(viable) != 1:
        return False
    if top.po_number not in {c.po_number for c in viable}:
        return False
    if gate.get("require_vendor_exact", True) and top.score.vendor_match <= 0:
        return False
    if gate.get("require_currency_match", True) and invoice_currency and po_currency:
        if invoice_currency.upper() != po_currency.upper():
            return False
    if not gate.get("allow_without_line_match", True) and _line_coverage(top) < 0.01:
        pass  # allowed when flag is true
    return True


def _vendor_amount_ambiguous(
    candidates: list[POCandidate],
    invoice_total: float | None,
    policy: dict,
) -> bool:
    """Two or more POs fit vendor+amount equally (Spec Section 11)."""
    gate = policy.get("unique_vendor_amount_match", {})
    tol = float(gate.get("max_tolerance_pct", 0.02))
    viable = [
        c
        for c in candidates
        if c.score.vendor_match > 0
        and c.score.amount_match >= gate.get("min_amount_match", 8)
        and _amount_fits_remaining(c, invoice_total, tol)
    ]
    return len(viable) >= 2


def _vendor_only_multiple(
    candidates: list[POCandidate],
    invoice_total: float | None,
    vendor_only_mode: bool,
) -> bool:
    """Vendor resolved but no amount/lines — multiple open POs (Spec Test 5)."""
    if not vendor_only_mode or invoice_total is not None:
        return False
    vendor_matches = [c for c in candidates if c.score.vendor_match > 0]
    return len(vendor_matches) >= 2


def _passes_no_po_evidence_gate(
    top: POCandidate,
    second: POCandidate | None,
    suggestion_mode: bool,
    policy: dict,
) -> bool:
    """Strong multi-signal match without printed PO number."""
    gate = policy.get("no_po_auto_match", {})
    if not gate.get("enabled", True) or not suggestion_mode:
        return False

    gap = top.score.total - (second.score.total if second else 0)
    coverage = _line_coverage(top)
    balance_ok = "potential_overbilling" not in top.flags

    checks = [
        top.score.vendor_match >= gate.get("min_vendor_match", 15),
        top.score.line_match >= gate.get("min_line_match", 14),
        top.score.amount_match >= gate.get("min_amount_match", 8),
        coverage >= gate.get("min_line_coverage", 0.85),
        gap >= gate.get("min_gap", 10),
        balance_ok or not gate.get("require_balance_ok", True),
        "potential_overbilling" not in top.flags
        or not gate.get("require_no_overbilling_flag", True),
    ]
    if gate.get("require_vendor_exact", True) and top.score.vendor_match <= 0:
        return False

    return all(checks)


def _passes_vendor_amount_no_po_auto_match(
    top: POCandidate,
    all_candidates: list[POCandidate],
    invoice_total: float | None,
    suggestion_mode: bool,
    policy: dict,
) -> bool:
    """Auto-match no-PO invoices when vendor + amount + single open PO align."""
    gate = policy.get("vendor_amount_no_po_auto_match", {})
    if not gate.get("enabled", True) or not suggestion_mode:
        return False

    if gate.get("require_single_open_po_for_vendor", True):
        vendor_pos = [c for c in all_candidates if c.score.vendor_match > 0]
        if len(vendor_pos) != 1:
            return False

    if gate.get("require_vendor_exact", True) and top.score.vendor_match <= 0:
        return False

    min_coverage = float(gate.get("max_line_coverage_required", 0.0))
    if _line_coverage(top) < min_coverage:
        return False

    if top.score.vendor_match < gate.get("min_vendor_match", 15):
        return False
    if top.score.amount_match < gate.get("min_amount_match", 8):
        return False

    if gate.get("require_balance_ok", True) and "potential_overbilling" in top.flags:
        return False

    return _amount_fits_remaining(
        top,
        invoice_total,
        float(gate.get("max_tolerance_pct", 0.15)),
        allow_partial_usage=True,
    )


def detect_ambiguity(
    candidates: list[POCandidate],
    suggestion_mode: bool = False,
    invoice_total: float | None = None,
    invoice_currency: str | None = None,
    po_currency: str | None = None,
    vendor_only_mode: bool = False,
    po_presence: str = "po_invoice",
) -> tuple[str, list[POCandidate]]:
    policy = load_matching_policy()
    amb = policy.get("ambiguity", {})

    ambiguous_gap = amb.get("ambiguous_gap", 5)
    auto_select_gap = amb.get("auto_select_gap", 15)
    exact_threshold = amb.get("exact_match_threshold", 95)
    high_conf_threshold = amb.get("high_confidence_threshold", 85)
    minimum_threshold = amb.get("minimum_match_threshold", 70)

    if not candidates:
        logger.info("Ambiguity: no candidates → unmatched")
        return "unmatched", []

    sorted_candidates = sorted(candidates, key=lambda c: c.score.total, reverse=True)
    top = sorted_candidates[0]
    top_score = top.score.total
    second = sorted_candidates[1] if len(sorted_candidates) > 1 else None
    gap = top_score - (second.score.total if second else 0)

    uva_gate = policy.get("unique_vendor_amount_match", {})
    auto_status = uva_gate.get("auto_status", "high_confidence_match")

    if _vendor_only_multiple(sorted_candidates, invoice_total, vendor_only_mode):
        logger.info("Ambiguity: multiple_candidates — vendor only, no amount")
        return "multiple_candidates", sorted_candidates[:5]

    if _vendor_amount_ambiguous(sorted_candidates, invoice_total, policy):
        logger.info("Ambiguity: ambiguous_match — multiple vendor+amount fits")
        return "ambiguous_match", sorted_candidates[:2]

    if _passes_unique_vendor_amount_gate(
        top, sorted_candidates, invoice_total, invoice_currency, po_currency, policy
    ):
        logger.info(
            "Ambiguity: %s via unique vendor+amount gate (po: %s)",
            auto_status,
            top.po_number,
        )
        return auto_status, [top]

    if _passes_no_po_evidence_gate(top, second, suggestion_mode, policy):
        logger.info(
            "Ambiguity: high_confidence_match via no-PO evidence gate "
            "(score: %.0f, gap: %.1f, po: %s)",
            top_score,
            gap,
            top.po_number,
        )
        return "high_confidence_match", [top]

    va_gate = policy.get("vendor_amount_no_po_auto_match", {})
    if _passes_vendor_amount_no_po_auto_match(
        top, sorted_candidates, invoice_total, suggestion_mode, policy
    ):
        auto_status = va_gate.get("auto_status", "high_confidence_match")
        logger.info(
            "Ambiguity: %s via vendor+amount no-PO gate (po: %s, score: %.0f)",
            auto_status,
            top.po_number,
            top_score,
        )
        return auto_status, [top]

    def _status_from_score(score: float, gap_ok: bool) -> str:
        if score >= exact_threshold:
            return "matched"
        if score >= high_conf_threshold:
            return "high_confidence_match"
        if score >= minimum_threshold and gap_ok:
            return "high_confidence_match"
        return "unmatched"

    if len(sorted_candidates) == 1:
        if suggestion_mode:
            if _passes_unique_vendor_amount_gate(
                top, sorted_candidates, invoice_total, invoice_currency, po_currency, policy
            ):
                return auto_status, [top]
            if top_score >= minimum_threshold * 0.5:
                review_status = _suggestion_review_status(po_presence)
                logger.info(
                    "Ambiguity (single, no-PO): %s (score: %.0f, evidence insufficient)",
                    review_status,
                    top_score,
                )
                return review_status, []
            logger.info("Ambiguity (single, no-PO): unmatched (score: %.0f)", top_score)
            return "unmatched", []

        status = _status_from_score(top_score, gap_ok=True)
        logger.info("Ambiguity (single): %s (score: %.0f)", status, top_score)
        return status, [top] if status != "unmatched" else []

    if gap < ambiguous_gap:
        logger.info(
            "Ambiguity: AMBIGUOUS (gap: %.1f, #%s=%.0f, #%s=%.0f)",
            gap,
            top.po_number,
            top_score,
            second.po_number if second else "?",
            second.score.total if second else 0,
        )
        return "ambiguous_match", sorted_candidates[:2]

    gap_ok = gap >= auto_select_gap
    status = _status_from_score(top_score, gap_ok=gap_ok)

    if status == "unmatched" and suggestion_mode and top_score >= minimum_threshold * 0.5:
        review_status = _suggestion_review_status(po_presence)
        logger.info(
            "Ambiguity: %s — suggestions available (top score %.0f)",
            review_status,
            top_score,
        )
        return review_status, []

    logger.info(
        "Ambiguity: %s (gap: %.1f, winner %s)",
        status,
        gap,
        top.po_number,
    )
    return status, [top] if status != "unmatched" else []
