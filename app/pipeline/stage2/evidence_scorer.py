"""
InvoiceFlow AI — Stage 2: Evidence-Based Scoring Engine

Policy-driven weighted match scores — per-candidate vendor alignment.
"""

import logging
from datetime import datetime

from app.models.match import ScoreBreakdown, LineMapping, EvidenceSignal
from app.pipeline.policy_loader import load_matching_policy
from app.services.vendor_identity import vendor_names_equivalent

logger = logging.getLogger(__name__)


class EvidenceScorer:
    """Computes weighted evidence scores for a PO candidate."""

    def __init__(self):
        policy = load_matching_policy()
        scoring = policy.get("scoring", {})
        self._max_po = scoring.get("max_po_match", 40)
        self._max_vendor = scoring.get("max_vendor_match", 20)
        self._max_line = scoring.get("max_line_match", 20)
        self._max_amount = scoring.get("max_amount_match", 10)
        self._max_historical = scoring.get("max_historical", 5)
        self._max_date = scoring.get("max_date_match", 5)
        self._retrieval_weights = scoring.get(
            "retrieval_weights",
            {
                "exact": 1.0,
                "normalized": 0.85,
                "reference": 0.75,
                "vendor_search": 0.55,
                "vendor_name": 0.5,
                "vendor_amount": 0.45,
                "source_record_po_hint": 0.55,
                "import_derived": 0.55,
                "fuzzy": 0.25,
                "broadcast": 0.1,
            },
        )
        self._amount_policy = scoring.get("amount", {})
        self._partial_full_score = self._amount_policy.get("partial_usage_full_score", True)

    def score(
        self,
        retrieval_method: str,
        retrieval_confidence: float,
        resolved_vendor_id: str | None,
        candidate_vendor_id: str,
        vendor_confidence: float,
        line_mappings: list[LineMapping],
        invoice_total: float | None,
        po_total: float,
        invoice_date: str | None,
        po_issue_date: str,
        po_remaining: float | None = None,
        balance_ok: bool = True,
        invoice_vendor_name: str | None = None,
        candidate_vendor_name: str | None = None,
    ) -> tuple[ScoreBreakdown, list[str]]:
        evidence: list[str] = []

        po_score = self._score_po_match(retrieval_method, retrieval_confidence)
        if po_score > 0:
            if retrieval_method == "source_record_po_hint":
                evidence.append(
                    f"PO hint from imported transaction data (not auto-bound): "
                    f"{po_score:.0f}/{self._max_po}"
                )
            elif retrieval_method == "import_derived":
                evidence.append(
                    f"PO from imported master (mirrored at upload): {po_score:.0f}/{self._max_po}"
                )
            else:
                evidence.append(f"PO match ({retrieval_method}): {po_score:.0f}/{self._max_po}")

        vendor_score = self._score_vendor_for_candidate(
            resolved_vendor_id,
            candidate_vendor_id,
            vendor_confidence,
            invoice_vendor_name=invoice_vendor_name,
            candidate_vendor_name=candidate_vendor_name,
        )
        if vendor_score > 0:
            evidence.append(f"Vendor verified: {vendor_score:.0f}/{self._max_vendor}")
        elif (
            resolved_vendor_id
            and candidate_vendor_id
            and resolved_vendor_id != candidate_vendor_id
            and not vendor_names_equivalent(invoice_vendor_name, candidate_vendor_name)
        ):
            evidence.append(
                f"Vendor conflict: invoice vendor {resolved_vendor_id} ≠ PO vendor {candidate_vendor_id}"
            )

        line_score = self._score_lines(line_mappings)
        if line_score > 0:
            matched = sum(1 for m in line_mappings if m.match_type != "unmatched")
            evidence.append(
                f"Line matching: {matched}/{len(line_mappings)} lines matched, "
                f"score {line_score:.0f}/{self._max_line}"
            )

        compare_amount = po_remaining if po_remaining is not None else po_total
        amount_score = self._score_amount(invoice_total, compare_amount, balance_ok)
        if amount_score > 0:
            label = "remaining" if po_remaining is not None else "total"
            evidence.append(
                f"Amount alignment vs PO {label}: {amount_score:.0f}/{self._max_amount}"
            )

        historical_score = 0.0
        date_score = self._score_date(invoice_date, po_issue_date)
        if date_score > 0:
            evidence.append(f"Date alignment: {date_score:.0f}/{self._max_date}")

        breakdown = ScoreBreakdown(
            po_match=round(po_score, 1),
            vendor_match=round(vendor_score, 1),
            line_match=round(line_score, 1),
            amount_match=round(amount_score, 1),
            historical_match=round(historical_score, 1),
            date_match=round(date_score, 1),
        )
        logger.info("Evidence score: %.0f/100", breakdown.total)
        return breakdown, evidence

    def build_structured_signals(
        self,
        breakdown: ScoreBreakdown,
        retrieval_method: str,
        balance_ok: bool,
        line_mappings: list[LineMapping],
    ) -> list[EvidenceSignal]:
        """Typed evidence signals for audit UI (Spec Section 15)."""
        coverage = 0.0
        if line_mappings:
            matched = sum(1 for m in line_mappings if m.match_type != "unmatched")
            coverage = matched / len(line_mappings)
        signals: list[EvidenceSignal] = []
        if retrieval_method == "source_record_po_hint":
            signals.append(
                EvidenceSignal(
                    signal="source_record_po_hint",
                    status="hint" if breakdown.po_match > 0 else "not_available",
                    score=breakdown.po_match,
                    max_score=float(self._max_po),
                    detail="PO reference from imported transaction data (informational only)",
                    source="source_records",
                )
            )
        signals.extend([
            EvidenceSignal(
                signal="po_reference",
                status="match" if breakdown.po_match > 0 else "not_available",
                score=breakdown.po_match,
                max_score=float(self._max_po),
                detail=f"Retrieval: {retrieval_method}",
                source="retrieval",
            ),
            EvidenceSignal(
                signal="vendor",
                status="exact_match" if breakdown.vendor_match >= self._max_vendor * 0.75 else "weak",
                score=breakdown.vendor_match,
                max_score=float(self._max_vendor),
                source="scorer",
            ),
            EvidenceSignal(
                signal="amount",
                status="exact_remaining_balance" if breakdown.amount_match >= self._max_amount * 0.8 else "weak",
                score=breakdown.amount_match,
                max_score=float(self._max_amount),
                source="scorer",
            ),
            EvidenceSignal(
                signal="line_match",
                status="match" if coverage >= 0.85 else ("partial" if coverage > 0 else "not_available"),
                score=breakdown.line_match,
                max_score=float(self._max_line),
                detail=f"Coverage {coverage:.0%}" if line_mappings else "No invoice lines",
                source="scorer",
            ),
            EvidenceSignal(
                signal="balance",
                status="within_balance" if balance_ok else "over_invoice",
                passed=balance_ok,
                source="balance",
            ),
        ])
        return signals

    def _score_po_match(self, method: str, confidence: float) -> float:
        weight = self._retrieval_weights.get(method, 0.1)
        return self._max_po * weight * confidence

    def _score_vendor_for_candidate(
        self,
        resolved_vendor_id: str | None,
        candidate_vendor_id: str,
        vendor_confidence: float,
        invoice_vendor_name: str | None = None,
        candidate_vendor_name: str | None = None,
    ) -> float:
        if (
            resolved_vendor_id
            and candidate_vendor_id
            and resolved_vendor_id == candidate_vendor_id
        ):
            confidence = vendor_confidence if vendor_confidence > 0 else 0.9
            return self._max_vendor * confidence

        if invoice_vendor_name and candidate_vendor_name:
            if vendor_names_equivalent(invoice_vendor_name, candidate_vendor_name):
                confidence = vendor_confidence if vendor_confidence > 0 else 0.9
                return self._max_vendor * confidence

        return 0.0

    def _score_lines(self, mappings: list[LineMapping]) -> float:
        if not mappings:
            return 0.0
        matched_lines = [m for m in mappings if m.match_type != "unmatched"]
        if not matched_lines:
            return 0.0
        match_ratio = len(matched_lines) / len(mappings)
        avg_similarity = sum(m.similarity_score for m in matched_lines) / len(matched_lines)
        combined = (match_ratio * 0.6) + (avg_similarity * 0.4)
        return self._max_line * combined

    def _score_amount(
        self,
        invoice_total: float | None,
        compare_amount: float,
        balance_ok: bool,
    ) -> float:
        if invoice_total is None or compare_amount <= 0:
            return 0.0

        if self._partial_full_score and balance_ok and invoice_total <= compare_amount:
            return float(self._max_amount)

        if invoice_total > compare_amount:
            over_ratio = (invoice_total - compare_amount) / compare_amount
            tolerance = self._amount_policy.get("over_remaining_tolerance_pct", 0.05)
            if over_ratio <= tolerance:
                return self._max_amount * 0.5
            return self._max_amount * 0.1

        ratio = min(invoice_total, compare_amount) / max(invoice_total, compare_amount)
        if ratio >= 0.95:
            return float(self._max_amount)
        if ratio >= 0.80:
            return self._max_amount * 0.7
        if ratio >= 0.60:
            return self._max_amount * 0.4
        return self._max_amount * 0.1

    def _score_date(self, invoice_date: str | None, po_issue_date: str) -> float:
        if not invoice_date or not po_issue_date:
            return 0.0
        try:
            inv_dt = datetime.strptime(invoice_date, "%Y-%m-%d")
            po_dt = datetime.strptime(po_issue_date, "%Y-%m-%d")
            days_diff = abs((inv_dt - po_dt).days)
            if days_diff <= 30:
                return float(self._max_date)
            if days_diff <= 90:
                return self._max_date * 0.7
            if days_diff <= 180:
                return self._max_date * 0.4
            return self._max_date * 0.1
        except ValueError:
            return 0.0
