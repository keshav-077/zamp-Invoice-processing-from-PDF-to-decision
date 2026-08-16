"""
InvoiceFlow AI — Evidence Profile Models

Structured extraction and matching evidence per Final Implementation Spec.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ExtractionQuality(str, Enum):
    """Stage 1 extraction quality — metadata, not a workflow stop switch."""

    COMPLETE = "extraction_complete"
    PARTIAL = "extraction_partial"
    WEAK = "extraction_weak"
    FAILED = "extraction_failed"


class EvidenceProfile(BaseModel):
    """What extraction actually provides for downstream matching and validation."""

    available: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    optional_missing: list[str] = Field(
        default_factory=list,
        description="Match/PO signals absent but not required for Stage 1 pass",
    )
    uncertain: list[str] = Field(default_factory=list)
    critical_missing: list[str] = Field(default_factory=list)
    matchable_signals: list[str] = Field(default_factory=list)
    reconciliation_status: str | None = Field(
        default=None, description="Reconciliation overall_status if computed"
    )


class CandidateEvidenceSignal(BaseModel):
    """Typed evidence for one PO candidate dimension (Spec Section 15)."""

    signal: str = Field(description="po_reference | vendor | amount | line_match | currency | balance")
    status: str = Field(default="not_available")
    score: float | None = None
    method: str | None = None
    detail: str = ""
    invoice_amount: float | None = None
    remaining_balance: float | None = None
    coverage: float | None = None


def to_legacy_routing_status(quality: ExtractionQuality, has_review_flags: bool) -> str:
    """Map extraction quality + approval review flags to legacy API status."""
    if quality == ExtractionQuality.FAILED:
        return "extraction_failed"
    if quality == ExtractionQuality.WEAK or has_review_flags:
        return "needs_human_review"
    return "stage1_passed"


def quality_from_profile(profile: EvidenceProfile, hard_failed: bool = False) -> ExtractionQuality:
    """Classify extraction quality — optional missing signals do not downgrade quality."""
    if hard_failed:
        return ExtractionQuality.FAILED
    if not profile.matchable_signals:
        return ExtractionQuality.WEAK
    if profile.critical_missing or profile.uncertain:
        return ExtractionQuality.PARTIAL
    return ExtractionQuality.COMPLETE
