"""Human-readable pipeline status messages for API and UI."""

from app.models.evidence import EvidenceProfile, ExtractionQuality
from app.models.match import MatchPackage


STAGE2_STATUS_LABELS = {
    "matched": "PO Matched",
    "high_confidence_match": "PO Matched (High Confidence)",
    "ambiguous_match": "Ambiguous PO Match",
    "partial_match": "Partial PO Match",
    "non_po_workflow": "Non-PO Workflow",
    "waiting_for_po": "PO Not Found in PO Master (invoice transactions may exist separately)",
    "suggested_po_match": "No PO on Invoice — Suggested PO Match Available",
    "waiting_for_grn": "Waiting for Goods Receipt",
    "closed_po_review": "Closed PO — Review Required",
    "unmatched": "PO Unmatched",
    "no_matching_evidence": "Insufficient Extraction for PO Matching",
    "multiple_candidates": "Multiple PO Candidates",
    "po_suggestions_rejected": "PO Suggestions Rejected",
}


def describe_extraction_quality(quality: ExtractionQuality | None) -> list[str]:
    if quality is None:
        return []
    labels = {
        ExtractionQuality.COMPLETE: "Extraction complete",
        ExtractionQuality.PARTIAL: "Extraction partial — some fields missing",
        ExtractionQuality.WEAK: "Extraction weak — limited matchable evidence",
        ExtractionQuality.FAILED: "Extraction failed",
    }
    return [f"📋 {labels.get(quality, quality.value)}"]


def describe_evidence_profile(profile: EvidenceProfile | None) -> list[str]:
    if profile is None:
        return []
    lines = ["📋 Extraction evidence profile:"]
    if profile.available:
        lines.append(f"  Available: {', '.join(profile.available)}")
    if profile.missing:
        lines.append(f"  Missing: {', '.join(profile.missing)}")
    if profile.matchable_signals:
        lines.append(f"  Matchable: {', '.join(profile.matchable_signals)}")
    return lines


def describe_stage2(match_package: MatchPackage | None, stage2_status: str = "") -> list[str]:
    """Build human-readable Stage 2 explanation lines."""
    if match_package is None:
        if stage2_status:
            return [f"📦 Stage 2: {STAGE2_STATUS_LABELS.get(stage2_status, stage2_status)}"]
        return []

    status = match_package.match_status
    lines = [f"📦 Stage 2: {STAGE2_STATUS_LABELS.get(status, status)}"]

    if match_package.explanation:
        exp = match_package.explanation
        lines.append(f"  {exp.summary}")
        lines.extend(f"  • {d}" for d in exp.details[:8])
    elif status == "no_matching_evidence":
        lines.append(
            "  Extraction was unable to provide enough information for PO matching."
        )
        lines.append("  PO matching found 0 candidates.")
    elif status == "non_po_workflow":
        lines.append(
            "ℹ️ No PO reference was found on the invoice — this is not a database lookup failure."
        )
    elif status == "waiting_for_po":
        po_ref = next(
            (e for e in match_package.evidence if e.startswith("PO reference:")),
            "PO reference present on invoice",
        )
        lines.append(f"⚠️ {po_ref} — no matching PO exists in the database yet.")
    elif status == "suggested_po_match":
        lines.append(
            "ℹ️ No PO on invoice — ranked PO suggestions available for optional confirmation."
        )
    elif match_package.evidence:
        lines.extend(f"• {item}" for item in match_package.evidence[:5])

    if match_package.flags:
        lines.append(f"🏷️ Flags: {', '.join(match_package.flags)}")

    return lines


def describe_stage3(overall_state: str, evidence_summary: list[str] | None = None) -> list[str]:
    """Build human-readable Stage 3 explanation lines."""
    if not overall_state:
        return []

    lines = [f"🛡️ Stage 3: {overall_state.replace('_', ' ').title()}"]
    if evidence_summary:
        lines.extend(f"• {item}" for item in evidence_summary[:5])
    return lines


def describe_stage4(decision: str, substate: str) -> list[str]:
    """Build human-readable Stage 4 explanation lines."""
    if not decision:
        return []
    detail = f" ({substate})" if substate else ""
    return [f"⚖️ Stage 4: {decision}{detail}"]
