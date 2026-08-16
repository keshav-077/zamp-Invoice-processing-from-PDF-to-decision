"""
InvoiceFlow AI — Stage 4 Decision Data Models

Defines the output schema for the Business Decision Engine:
- RuleEvaluation:      One rule checked during decision
- PolicyResolution:    Effective policy resolved for the invoice
- AuthorityResolution: Approval authority + SoD result
- RoutingDecision:     Routing target + SLA
- DecisionTrace:       Complete explainability contract
- DecisionRecord:      The immutable Stage 4 output for Stage 5

Decision hierarchy (PRD Section 8):
  Decision:     APPROVE / REVIEW_REQUIRED / REJECT / WAITING_FOR_VALIDATION
  Substate:     AUTO_APPROVED, APPROVAL_REQUIRED, STANDARD_REVIEW, etc.
  Reason codes: Machine-readable explanation codes
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field
import uuid


# ═══════════════════════════════════════════════════════════
# Decision Types
# ═══════════════════════════════════════════════════════════

Decision = Literal[
    "APPROVE", "REVIEW_REQUIRED", "REJECT", "WAITING_FOR_VALIDATION"
]

DecisionSubstate = Literal[
    # APPROVE substates
    "AUTO_APPROVED",
    "APPROVAL_REQUIRED",
    # REVIEW subtypes
    "STANDARD_REVIEW",
    "HIGH_PRIORITY_REVIEW",
    "FRAUD_REVIEW",
    "VENDOR_SECURITY_REVIEW",
    "POLICY_EXCEPTION_REVIEW",
    # REJECT subtype
    "TERMINAL_REJECT",
    # WAITING subtypes
    "WAITING_FOR_GRN",
    "WAITING_FOR_REQUIRED_DATA",
    "REVALIDATION_REQUIRED",
    "POLICY_CONFIGURATION_ERROR",
]

MaterialityTier = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RuleResult = Literal["TRIGGERED", "NOT_TRIGGERED", "NOT_APPLICABLE", "ERROR"]


# ═══════════════════════════════════════════════════════════
# Rule Evaluation
# ═══════════════════════════════════════════════════════════

class RuleEvaluation(BaseModel):
    """Result of evaluating a single business rule."""

    rule_id: str = Field(description="Rule identifier (e.g., 'BANK_CHANGE_OVERRIDE')")
    rule_version: str = Field(default="", description="Rule version")
    result: RuleResult = Field(description="TRIGGERED / NOT_TRIGGERED / NOT_APPLICABLE / ERROR")
    priority: int = Field(default=9, description="Policy precedence priority (P0-P9)")
    detail: str = Field(default="", description="Human-readable detail")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Rule input values")


# ═══════════════════════════════════════════════════════════
# Policy Resolution
# ═══════════════════════════════════════════════════════════

class PolicyResolution(BaseModel):
    """The effective policy resolved for this invoice."""

    policy_id: str = Field(default="AP-DEFAULT", description="Policy identifier")
    policy_version: str = Field(default="AP-2026.08.1", description="Policy version")
    materiality_tier: MaterialityTier = Field(default="MEDIUM", description="Amount-based tier")
    auto_approve_eligible: bool = Field(
        default=False, description="Whether auto-approval is permitted"
    )
    approval_limit: float = Field(default=0.0, description="Max auto-approve amount")
    risk_tier: str = Field(default="STANDARD", description="Vendor risk tier")
    resolved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="When policy was resolved",
    )


# ═══════════════════════════════════════════════════════════
# Authority Resolution
# ═══════════════════════════════════════════════════════════

class AuthorityResolution(BaseModel):
    """Approval authority + segregation of duties result."""

    required: bool = Field(default=False, description="Whether approval is required")
    required_limit: float = Field(default=0.0, description="Approval limit required")
    approver_group: str = Field(default="", description="Target approval group")
    sod_check_passed: bool = Field(default=True, description="SoD constraint passed")
    sod_detail: str = Field(default="", description="SoD check detail")
    delegation_active: bool = Field(default=False, description="Whether delegation is active")
    dual_control_required: bool = Field(
        default=False, description="Whether dual-control is required"
    )
    eligible_approvers: list[str] = Field(
        default_factory=list, description="Eligible approver identifiers"
    )


# ═══════════════════════════════════════════════════════════
# Routing Decision
# ═══════════════════════════════════════════════════════════

class RoutingDecision(BaseModel):
    """Routing target + SLA assignment."""

    target: str | None = Field(default=None, description="Routing target queue/group")
    priority: str = Field(default="NORMAL", description="Routing priority")
    sla_hours: int = Field(default=48, description="SLA hours for resolution")
    resume_condition: str | None = Field(
        default=None, description="Condition to resume (for WAITING states)"
    )


# ═══════════════════════════════════════════════════════════
# Decision Trace (Explainability Contract)
# ═══════════════════════════════════════════════════════════

class DecisionTrace(BaseModel):
    """
    Complete decision trace for Stage 5 explainability.

    Stage 5 must be able to explain Stage 4 without re-running the decision.
    """

    rules_evaluated: list[RuleEvaluation] = Field(
        default_factory=list, description="Every rule checked"
    )
    triggered_rules: list[str] = Field(
        default_factory=list, description="Rule IDs that fired"
    )
    policy: PolicyResolution = Field(
        default_factory=PolicyResolution, description="Effective policy used"
    )
    authority: AuthorityResolution = Field(
        default_factory=AuthorityResolution, description="Authority resolution result"
    )
    routing: RoutingDecision = Field(
        default_factory=RoutingDecision, description="Routing decision"
    )
    stage3_state_used: str = Field(
        default="", description="Stage 3 overall_state consumed"
    )
    stage3_reason_codes_used: list[str] = Field(
        default_factory=list, description="Stage 3 reason codes consumed"
    )
    decision_path: list[str] = Field(
        default_factory=list,
        description="Ordered list of decision steps taken (audit trail)",
    )


# ═══════════════════════════════════════════════════════════
# Decision Record (Immutable Stage 4 Output)
# ═══════════════════════════════════════════════════════════

class DecisionRecord(BaseModel):
    """
    The immutable Stage 4 output — a complete business decision record.

    This is the contract between Stage 4 and Stage 5.
    After finalization, this record is never rewritten.
    """

    # --- Identity ---
    decision_id: str = Field(
        default_factory=lambda: f"DEC-{uuid.uuid4().hex[:12].upper()}",
        description="Unique decision identifier",
    )
    invoice_id: str = Field(description="Invoice document ID")
    validation_run_id: str = Field(description="Stage 3 validation run ID consumed")

    # --- Decision ---
    decision: Decision = Field(description="Terminal business disposition")
    decision_substate: DecisionSubstate = Field(description="Decision subtype")
    reason_codes: list[str] = Field(
        default_factory=list, description="Machine-readable reason codes"
    )

    # --- Decision Trace ---
    trace: DecisionTrace = Field(
        default_factory=DecisionTrace, description="Complete decision trace"
    )

    # --- Evidence ---
    evidence_refs: list[str] = Field(
        default_factory=list, description="Evidence references from Stage 3"
    )
    evidence_summary: list[str] = Field(
        default_factory=list, description="Human-readable evidence trail"
    )

    # --- Audit ---
    engine_version: str = Field(
        default="stage4-v2.0", description="Stage 4 engine version"
    )
    decided_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="When decision was made",
    )
    processing_time_seconds: float = Field(
        default=0.0, description="Stage 4 processing time"
    )

    # --- Stage 5 routing ---
    next_action: str = Field(
        default="STAGE5_EXPLAIN",
        description="Next recommended action",
    )
