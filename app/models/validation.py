"""
InvoiceFlow AI — Stage 3 Validation Data Models

Defines the output schema for the Validation Engine:
- ValidationCheck: Result of a single validation engine
- ControlRecord: Hold/Block control state
- ValidationReport: Complete Stage 3 output for Stage 4

Four separate status dimensions:
  Check status:           PASS / FLAG / FAIL / NOT_APPLICABLE / UNAVAILABLE
  Processing state:       COMPLETED / FAILED
  Overall validation:     VALIDATED / REVIEW_REQUIRED / HOLD / BLOCKED / VALIDATION_INCOMPLETE
  Reason codes:           Machine-readable explanation codes
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field
import uuid


# ═══════════════════════════════════════════════════════════
# Check Status — one validator's result
# ═══════════════════════════════════════════════════════════

CheckStatus = Literal["PASS", "FLAG", "FAIL", "NOT_APPLICABLE", "UNAVAILABLE"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ControlType = Literal["HOLD", "BLOCK"]
ControlState = Literal["OPEN", "RELEASED", "ESCALATED"]
OverallState = Literal[
    "VALIDATED", "REVIEW_REQUIRED", "HOLD", "BLOCKED", "VALIDATION_INCOMPLETE"
]
ProcessingState = Literal["COMPLETED", "FAILED"]


class ValidationCheck(BaseModel):
    """Result of a single validation engine check."""

    check_id: str = Field(description="Engine identifier (e.g., 'amount_variance')")
    status: CheckStatus = Field(description="Check result status")
    reason_code: str = Field(default="", description="Machine-readable reason code")
    severity: Severity = Field(default="LOW", description="Finding severity")

    # Rule context
    rule_id: str = Field(default="", description="Business rule identifier")
    rule_version: str = Field(default="", description="Rule version for reproducibility")

    # Evidence
    inputs: dict[str, Any] = Field(
        default_factory=dict, description="Input values used in check"
    )
    calculation: dict[str, Any] = Field(
        default_factory=dict, description="Intermediate calculation results"
    )
    evidence: list[str] = Field(
        default_factory=list, description="Human-readable evidence strings"
    )
    evidence_refs: list[str] = Field(
        default_factory=list, description="Source references (e.g., 'PO123:LINE5')"
    )


class FraudSignal(BaseModel):
    """A single fraud/anomaly signal (not adjudication)."""

    signal_type: str = Field(description="Signal identifier")
    severity: Severity = Field(default="LOW")
    description: str = Field(description="Human-readable signal description")
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Supporting evidence"
    )


class ControlRecord(BaseModel):
    """A Hold or Block control created by Stage 3."""

    control_id: str = Field(
        default_factory=lambda: f"CTRL-{uuid.uuid4().hex[:8].upper()}",
        description="Unique control identifier",
    )
    control_type: ControlType = Field(description="HOLD or BLOCK")
    reason_code: str = Field(description="Machine-readable reason")
    state: ControlState = Field(default="OPEN", description="Current control state")
    check_id: str = Field(default="", description="Source validation check")
    detail: str = Field(default="", description="Human-readable detail")
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="When control was created",
    )


class SourceSnapshots(BaseModel):
    """Records exact data versions used for reproducibility."""

    stage1: str = Field(default="", description="Stage 1 snapshot reference")
    stage2: str = Field(default="", description="Stage 2 snapshot reference")
    po: str = Field(default="", description="PO version reference")
    vendor: str = Field(default="", description="Vendor master version reference")
    grn: str = Field(default="", description="GRN version reference")
    extraction: dict = Field(
        default_factory=dict,
        description="Key extraction fields for approval eligibility checks",
    )


class RevalidationInfo(BaseModel):
    """Revalidation metadata."""

    eligible: bool = Field(default=False, description="Whether revalidation is possible")
    parent_run_id: str | None = Field(
        default=None, description="Previous run this revalidation supersedes"
    )
    trigger: str = Field(
        default="", description="What triggered this run (initial, correction, grn_posted, etc.)"
    )


class ValidationReport(BaseModel):
    """
    Complete Stage 3 output — the Validation Report for Stage 4.

    Every invoice processed through Stage 3 produces exactly one ValidationReport.
    The overall_state is the enterprise control result before Stage 4 decision.
    """

    # --- Identity ---
    validation_run_id: str = Field(
        default_factory=lambda: f"VR-{uuid.uuid4().hex[:12].upper()}",
        description="Unique validation run identifier",
    )
    invoice_id: str = Field(description="Document ID from Stage 1/2")

    # --- States ---
    processing_state: ProcessingState = Field(
        default="COMPLETED", description="Technical execution state"
    )
    overall_state: OverallState = Field(
        description="Business-control result before Stage 4 decision"
    )
    reason_codes: list[str] = Field(
        default_factory=list, description="Machine-readable reason codes"
    )

    # --- Check Results ---
    checks: dict[str, ValidationCheck] = Field(
        default_factory=dict,
        description="Results from each validation engine",
    )

    # --- Controls ---
    controls: list[ControlRecord] = Field(
        default_factory=list, description="Active Hold/Block controls"
    )

    # --- Evidence ---
    evidence_summary: list[str] = Field(
        default_factory=list, description="Top-level evidence trail"
    )

    # --- Fraud Signals ---
    fraud_signals: list[FraudSignal] = Field(
        default_factory=list, description="Fraud/anomaly signals (not adjudication)"
    )

    # --- Versioning & Reproducibility ---
    policy_version: str = Field(
        default="AP-2026.08.1", description="Policy version used"
    )
    source_snapshots: SourceSnapshots = Field(
        default_factory=SourceSnapshots, description="Data versions used"
    )

    # --- Revalidation ---
    revalidation: RevalidationInfo = Field(
        default_factory=lambda: RevalidationInfo(trigger="initial"),
        description="Revalidation metadata",
    )

    # --- Timing ---
    processing_time_seconds: float = Field(
        default=0.0, description="Stage 3 processing time"
    )
    started_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="When validation started",
    )
    completed_at: str = Field(default="", description="When validation completed")

    # --- Stage 4 routing ---
    next_action: str = Field(
        default="STAGE4_DECISION",
        description="Next recommended action",
    )
