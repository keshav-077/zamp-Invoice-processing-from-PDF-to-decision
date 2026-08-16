"""Build structured Stage 2 explanations (Spec Section 18)."""

from __future__ import annotations

from app.models.evidence import EvidenceProfile
from app.models.match import MatchExplanation, MatchPackage, POCandidate


def build_match_explanation(
    match_status: str,
    selected: list[POCandidate],
    all_candidates: list[POCandidate],
    evidence_profile: EvidenceProfile | None = None,
) -> MatchExplanation:
    viable = [c for c in all_candidates if c.score.total > 0 or c.score.vendor_match > 0]
    explanation = MatchExplanation(
        candidates_searched=len(all_candidates),
        candidates_viable=len(viable),
        matched_po_numbers=[c.po_number for c in selected],
    )

    if evidence_profile:
        explanation.extraction_available = list(evidence_profile.available)
        explanation.extraction_missing = list(evidence_profile.missing)

    if match_status == "no_matching_evidence":
        explanation.summary = (
            "Extraction was unable to provide enough information for PO matching."
        )
        explanation.details = [
            "PO matching found 0 candidates.",
        ]
        if evidence_profile and evidence_profile.available:
            explanation.details.insert(
                0,
                f"Available: {', '.join(evidence_profile.available)}",
            )
        if evidence_profile and evidence_profile.missing:
            explanation.details.append(
                f"Missing: {', '.join(evidence_profile.missing)}"
            )
        return explanation

    if match_status in ("matched", "high_confidence_match") and len(selected) == 1:
        top = selected[0]
        explanation.summary = "One open PO uniquely matched the available evidence."
        explanation.details = [
            f"Matched PO: {top.po_number}",
        ]
        if top.score.vendor_match > 0:
            explanation.details.append("Vendor matched exactly.")
        if top.score.amount_match > 0:
            explanation.details.append(
                "Invoice amount aligns with remaining PO balance."
            )
        if top.score.line_match > 0:
            explanation.details.append("Line items matched PO lines.")
        if top.retrieval_method == "source_record_po_hint":
            explanation.details.append(
                "PO candidate surfaced from imported transaction po_reference (hint only)."
            )
        explanation.details.append("No contradictory evidence was found.")
        return explanation

    if match_status in ("ambiguous_match", "multiple_candidates"):
        explanation.summary = (
            "Available evidence was insufficient to distinguish PO candidates."
        )
        explanation.details = [
            f"PO matching found {len(viable)} viable candidate(s).",
        ]
        for c in viable[:5]:
            explanation.details.append(
                f"Candidate: {c.po_number} (score {c.score.total:.0f})"
            )
        if evidence_profile and evidence_profile.missing:
            explanation.details.append(
                f"Missing: {', '.join(evidence_profile.missing)}"
            )
        return explanation

    if match_status == "unmatched" and not viable:
        explanation.summary = "No open PO matched the extracted evidence."
        explanation.details = [
            "PO matching found 0 viable candidates.",
        ]
        if evidence_profile:
            if evidence_profile.available:
                explanation.details.insert(
                    0,
                    f"Available: {', '.join(evidence_profile.available)}",
                )
            if evidence_profile.missing:
                explanation.details.append(
                    f"Missing: {', '.join(evidence_profile.missing)}"
                )
        return explanation

    if match_status == "waiting_for_po":
        explanation.summary = "PO reference or evidence insufficient for confident match."
        explanation.details = [
            f"Ranked {len(all_candidates)} candidate(s) for human review.",
        ]
        return explanation

    if match_status == "suggested_po_match":
        explanation.summary = "No PO on invoice — suggested PO match available for confirmation."
        explanation.details = [
            f"Ranked {len(all_candidates)} candidate(s) by vendor, amount, and lines.",
        ]
        return explanation

    explanation.summary = f"PO resolution outcome: {match_status}"
    return explanation


def attach_explanation(package: MatchPackage, all_candidates: list[POCandidate]) -> MatchPackage:
    """Set explanation and next_stage on match package."""
    explanation = build_match_explanation(
        package.match_status,
        package.matched_pos,
        all_candidates,
        package.evidence_profile,
    )
    package.explanation = explanation
    package.candidate_count = len(all_candidates)
    if package.match_status in ("matched", "high_confidence_match", "partial_match"):
        package.next_stage = "validation"
    elif package.match_status in (
        "ambiguous_match",
        "unmatched",
        "no_matching_evidence",
        "multiple_candidates",
        "waiting_for_po",
        "suggested_po_match",
    ):
        package.next_stage = "human_review"
    return package
