"""
InvoiceFlow AI — Stage 5 Explanation Data Models

Defines the v3.0 Explanation Object schema:
- UpstreamArtifact:      Reference to a Stage 1-4 artifact
- NarrativeEntry:        One line of deterministic narrative
- ControlVerification:   Proof that a required control occurred
- EvidenceGap:           Explicit missing evidence
- HumanAction:           Reviewer annotation (additive only)
- SamplingAudit:         Sampling review outcome
- IntegrityProof:        Hash chain metadata
- ExplanationSnapshot:   The canonical Stage 5 output

Primary invariant:
  Stage 5 explains and proves; it never decides or re-derives.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field
import uuid


# ═══════════════════════════════════════════════════════════
# Explanation Status
# ═══════════════════════════════════════════════════════════

ExplanationStatus = Literal["COMPLETE", "INCOMPLETE"]


# ═══════════════════════════════════════════════════════════
# Upstream Artifact Reference
# ═══════════════════════════════════════════════════════════

class UpstreamArtifact(BaseModel):
    """Reference to a Stage 1-4 artifact snapshot."""

    stage: int = Field(description="Pipeline stage (1-4)")
    artifact_id: str = Field(description="Artifact identifier")
    artifact_type: str = Field(default="", description="Type of artifact")
    artifact_version: str = Field(default="", description="Version/run ID")
    artifact_hash: str = Field(default="", description="SHA-256 content hash")
    resolved: bool = Field(default=True, description="Whether artifact was resolvable")


# ═══════════════════════════════════════════════════════════
# Narrative Entry
# ═══════════════════════════════════════════════════════════

class NarrativeEntry(BaseModel):
    """One line of deterministic explanation narrative."""

    step: int = Field(description="Narrative step number")
    category: str = Field(description="Category (e.g., 'extraction', 'validation', 'decision')")
    text: str = Field(description="Human-readable explanation text")
    source_rule_id: str = Field(default="", description="Source rule that generated this line")
    evidence_ref: str = Field(default="", description="Reference to supporting evidence")
    icon: str = Field(default="", description="Display icon hint (e.g., '✅', '❌', '⚠️')")


# ═══════════════════════════════════════════════════════════
# Control Verification
# ═══════════════════════════════════════════════════════════

ControlStatus = Literal[
    "VERIFIED", "PENDING", "UNVERIFIED", "NO_RECORD_FOUND",
    "NOT_REQUIRED", "VERIFICATION_FAILED",
]


class ControlVerification(BaseModel):
    """Proof that a required control occurred (or explicit gap)."""

    control_id: str = Field(description="Control identifier")
    control_type: str = Field(description="Type (e.g., 'APPROVAL', 'BANK_VERIFICATION')")
    status: ControlStatus = Field(description="Verification status")
    verified_by: str = Field(default="", description="Who/what verified")
    verified_at: str = Field(default="", description="When verified")
    evidence: str = Field(default="", description="Verification evidence")
    gap_reason: str = Field(
        default="",
        description="If not verified, why (machine-readable)",
    )


# ═══════════════════════════════════════════════════════════
# Evidence Gap
# ═══════════════════════════════════════════════════════════

class EvidenceGap(BaseModel):
    """Explicit record of missing evidence — never inferred."""

    gap_id: str = Field(
        default_factory=lambda: f"GAP-{uuid.uuid4().hex[:8].upper()}",
        description="Gap identifier",
    )
    stage: int = Field(description="Which stage the gap is from")
    artifact_type: str = Field(description="What is missing")
    reason: str = Field(description="Why it is missing")
    impact: str = Field(default="", description="Impact on explanation")
    resolution: str = Field(default="", description="How to resolve")


# ═══════════════════════════════════════════════════════════
# Human Action (additive only — never modifies original)
# ═══════════════════════════════════════════════════════════

class HumanAction(BaseModel):
    """Reviewer annotation — additive record, original unchanged."""

    action_id: str = Field(
        default_factory=lambda: f"HA-{uuid.uuid4().hex[:8].upper()}",
        description="Action identifier",
    )
    action_type: str = Field(
        description="Type (e.g., 'REVIEW', 'COMMENT', 'OVERRIDE', 'APPROVAL')"
    )
    actor_id: str = Field(description="Who performed the action")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    detail: str = Field(default="", description="Action detail/comment")
    outcome: str = Field(default="", description="Action outcome")


# ═══════════════════════════════════════════════════════════
# Sampling Audit
# ═══════════════════════════════════════════════════════════

class SamplingAudit(BaseModel):
    """Sampling review outcome for AUTO_APPROVE decisions."""

    selected: bool = Field(default=False, description="Whether selected for sampling")
    selection_method: str = Field(default="", description="Random/risk-weighted")
    selection_basis: str = Field(default="", description="Selection criteria")
    reviewer_id: str = Field(default="", description="Reviewer identity")
    reviewed_at: str = Field(default="", description="When reviewed")
    outcome: str = Field(default="", description="CONFIRMED_CORRECT / ERROR_FOUND")
    findings: str = Field(default="", description="Reviewer findings")


# ═══════════════════════════════════════════════════════════
# Integrity Proof (Hash Chain)
# ═══════════════════════════════════════════════════════════

class IntegrityProof(BaseModel):
    """Hash chain metadata for tamper evidence."""

    algorithm: str = Field(default="SHA-256", description="Hash algorithm")
    content_hash: str = Field(default="", description="SHA-256 of canonical explanation")
    previous_hash: str = Field(default="GENESIS", description="Previous record hash")
    ledger_sequence: int = Field(default=0, description="Audit ledger sequence number")


# ═══════════════════════════════════════════════════════════
# Explanation Snapshot (Canonical Stage 5 Output)
# ═══════════════════════════════════════════════════════════

class ExplanationSnapshot(BaseModel):
    """
    The canonical Stage 5 output — a complete, deterministic explanation.

    This record is append-only and never rewritten.
    Corrections create new linked records.
    """

    # --- Identity ---
    explanation_id: str = Field(
        default_factory=lambda: f"EXP-{uuid.uuid4().hex[:12].upper()}",
        description="Unique explanation identifier",
    )
    explanation_schema_version: str = Field(
        default="3.0", description="Explanation schema version"
    )
    tenant_id: str = Field(
        default="TENANT-DEFAULT", description="Tenant scope"
    )

    # --- References ---
    decision_id: str = Field(description="Stage 4 decision ID")
    invoice_id: str = Field(description="Invoice document ID")
    validation_run_id: str = Field(default="", description="Stage 3 run ID")

    # --- Status ---
    explanation_status: ExplanationStatus = Field(
        default="COMPLETE", description="COMPLETE or INCOMPLETE"
    )

    # --- Policy ---
    policy_version: str = Field(default="", description="Policy version used")
    policy_hash: str = Field(default="", description="SHA-256 of policy artifact")

    # --- Decision Echo ---
    decision_outcome: str = Field(default="", description="Decision outcome echo")
    decision_substate: str = Field(default="", description="Decision substate echo")

    # --- Upstream Artifacts ---
    upstream_artifacts: list[UpstreamArtifact] = Field(
        default_factory=list, description="Stage 1-4 artifact references"
    )

    # --- Narrative ---
    narrative: list[NarrativeEntry] = Field(
        default_factory=list, description="Deterministic explanation narrative"
    )

    # --- Rule Trace Echo ---
    rule_trace_summary: list[dict] = Field(
        default_factory=list, description="Summarized rule trace from Stage 4"
    )

    # --- Routing Echo ---
    routing: dict = Field(
        default_factory=dict, description="Routing decision echo"
    )
    authority: dict = Field(
        default_factory=dict, description="Authority resolution echo"
    )

    # --- Control Verification ---
    control_verifications: list[ControlVerification] = Field(
        default_factory=list, description="Control verification records"
    )

    # --- Evidence ---
    evidence_refs: list[str] = Field(
        default_factory=list, description="Evidence references"
    )
    evidence_summary: list[str] = Field(
        default_factory=list, description="Human-readable evidence summary"
    )

    # --- Gaps ---
    gaps: list[EvidenceGap] = Field(
        default_factory=list, description="Explicit missing evidence"
    )

    # --- Human Actions ---
    human_actions: list[HumanAction] = Field(
        default_factory=list, description="Additive reviewer annotations"
    )

    # --- Sampling ---
    sampling_audit: SamplingAudit = Field(
        default_factory=SamplingAudit, description="Sampling audit record"
    )

    # --- Integrity ---
    integrity: IntegrityProof = Field(
        default_factory=IntegrityProof, description="Hash chain proof"
    )

    # --- Audit ---
    engine_version: str = Field(
        default="stage5-v3.0", description="Stage 5 engine version"
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="When explanation was generated",
    )
    processing_time_seconds: float = Field(
        default=0.0, description="Stage 5 processing time"
    )
