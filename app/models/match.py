"""
InvoiceFlow AI — Stage 2 Match Result Data Models

Defines the output schema for the PO Matching Engine:
- MatchPackage: Complete Stage 2 output for Stage 3
- POCandidate: A scored PO candidate with evidence
- LineMapping: Invoice line → PO line mapping
- ScoreBreakdown: Weighted evidence scores
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, computed_field

from app.models.evidence import CandidateEvidenceSignal, EvidenceProfile


class EvidenceSignal(BaseModel):
    """Structured evidence signal for ranking and audit (Spec Section 15)."""

    signal: str = Field(description="Evidence dimension name")
    status: str = Field(default="not_available")
    score: float | None = None
    max_score: float | None = None
    threshold: float | None = None
    passed: bool | None = None
    detail: str = ""
    source: str = Field(default="", description="scorer | gate | retrieval | balance")


class MatchExplanation(BaseModel):
    """Structured Stage 2 explanation for UI and audit (Spec Section 18)."""

    summary: str = ""
    details: list[str] = Field(default_factory=list)
    extraction_available: list[str] = Field(default_factory=list)
    extraction_missing: list[str] = Field(default_factory=list)
    candidates_searched: int = 0
    candidates_viable: int = 0
    matched_po_numbers: list[str] = Field(default_factory=list)


class LineMapping(BaseModel):
    """Maps a single invoice line to a PO line."""
    invoice_line: int = Field(description="Invoice line number (1-indexed)")
    po_number: str = Field(description="Matched PO number")
    po_line: int = Field(description="Matched PO line number (1-indexed)")
    match_type: Literal["exact", "semantic", "unmatched"] = Field(
        description="How the match was determined"
    )
    similarity_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Similarity score between invoice and PO line descriptions"
    )
    detail: str = Field(default="", description="Human-readable match explanation")


class ScoreBreakdown(BaseModel):
    """Weighted evidence scoring — every point is traceable."""
    po_match: float = Field(default=0.0, description="PO number match score (max 40)")
    vendor_match: float = Field(default=0.0, description="Vendor resolution score (max 20)")
    line_match: float = Field(default=0.0, description="Line-level match score (max 20)")
    amount_match: float = Field(default=0.0, description="Amount alignment score (max 10)")
    historical_match: float = Field(default=0.0, description="Historical pattern score (max 5)")
    date_match: float = Field(default=0.0, description="Date alignment score (max 5)")

    @computed_field
    @property
    def total(self) -> float:
        """Total weighted score (max 100)."""
        return (
            self.po_match + self.vendor_match + self.line_match
            + self.amount_match + self.historical_match + self.date_match
        )


class POCandidate(BaseModel):
    """A scored PO candidate with full evidence trail."""
    po_number: str = Field(description="PO number")
    vendor_id: str = Field(description="Matched vendor ID")
    vendor_name: str = Field(default="", description="Vendor name")
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    line_mappings: list[LineMapping] = Field(
        default_factory=list, description="Line-level match details"
    )
    flags: list[str] = Field(
        default_factory=list, description="Warning flags (e.g., 'closed_po', 'overbilling')"
    )
    evidence: list[str] = Field(
        default_factory=list, description="Human-readable evidence strings"
    )
    structured_evidence: list[EvidenceSignal | CandidateEvidenceSignal] = Field(
        default_factory=list, description="Typed evidence signals"
    )
    retrieval_method: str = Field(default="", description="How this candidate was retrieved")
    import_derived: bool = Field(
        default=False, description="PO master row mirrored from user CSV import"
    )
    po_status: str = Field(default="open", description="PO status at match time")
    po_type: str = Field(default="standard", description="PO type")
    remaining_balance: float = Field(default=0.0, description="PO remaining balance")


# Valid match states (Stage 2 state machine)
MATCH_STATES = {
    "matched",
    "high_confidence_match",
    "ambiguous_match",
    "partial_match",
    "non_po_workflow",
    "waiting_for_po",
    "suggested_po_match",
    "waiting_for_grn",
    "closed_po_review",
    "unmatched",
    "no_matching_evidence",
    "multiple_candidates",
    "po_suggestions_rejected",
}

# States that allow Stage 3 full validation
VALIDATION_ELIGIBLE_STATES = {
    "matched",
    "high_confidence_match",
    "partial_match",
    "ambiguous_match",
    "waiting_for_grn",
    "closed_po_review",
    "non_po_workflow",
}


def validation_allowed(match_package: MatchPackage) -> bool:
    """Single source of truth: contract gate decides if Stage 3+ may run."""
    from app.pipeline.stage3.contract_gate import validate_contract

    gate = validate_contract(match_package.invoice_id, match_package)
    return gate.is_valid and gate.validation_mode in ("full", "limited")


class MatchPackage(BaseModel):
    """
    Complete Stage 2 output — the match result package for Stage 3.

    Every invoice processed through Stage 2 produces exactly one MatchPackage.
    The match_status is the terminal state from the Stage 2 state machine.
    """
    invoice_id: str = Field(description="Document ID from Stage 1")
    match_status: str = Field(description="Terminal match state")
    matched_pos: list[POCandidate] = Field(
        default_factory=list, description="Scored PO candidates (ranked by score)"
    )
    unmatched_lines: list[int] = Field(
        default_factory=list, description="Invoice line numbers with no PO match"
    )
    flags: list[str] = Field(
        default_factory=list, description="Top-level match flags"
    )
    evidence: list[str] = Field(
        default_factory=list, description="Top-level evidence trail"
    )
    processing_time_seconds: float = Field(
        default=0.0, description="Stage 2 processing time"
    )

    # --- Stage 2 internal routing info ---
    confidence_gate_action: str = Field(
        default="", description="Confidence gate result: trust / validate / expand"
    )
    po_presence: str = Field(
        default="", description="PO presence result: po_invoice / non_po"
    )
    suggestion_mode: bool = Field(
        default=False, description="Whether Stage 2 ran in suggestion-only mode"
    )
    resolved_invoice_vendor_id: str | None = Field(
        default=None, description="Vendor ID resolved from invoice extraction"
    )
    vendor_master_status: str = Field(
        default="unresolved",
        description="master_hit | po_aligned | unresolved — vendor ID provenance for UI",
    )
    match_provenance: str = Field(
        default="",
        description="How match was established: authoritative_po, evidence, human_confirmed",
    )
    suggested_candidates: list[POCandidate] = Field(
        default_factory=list,
        description="Top-N PO candidates for human review (even when auto-match fails)"
    )
    evidence_profile: EvidenceProfile | None = Field(
        default=None, description="Extraction evidence profile passed from Stage 1"
    )
    explanation: MatchExplanation | None = Field(
        default=None, description="Structured match explanation"
    )
    candidate_count: int = Field(default=0, description="Total candidates evaluated")
    next_stage: str = Field(
        default="", description="validation | human_review | none"
    )
