"""
InvoiceFlow AI — Pipeline Result & Audit Trail Data Model

The PipelineResult captures the complete audit trail for one invoice run.
All intermediate results are preserved so decisions are reproducible
without re-calling the Vision LLM.
"""

from __future__ import annotations
from datetime import datetime
from typing import Literal, TYPE_CHECKING
from pydantic import BaseModel, Field

from app.models.extraction import InvoiceExtraction
from app.models.verification import VerificationResult
from app.models.arithmetic import ArithmeticResult
from app.models.reconciliation import ReconciliationResult
from app.models.evidence import EvidenceProfile, ExtractionQuality
from app.models.page import PageClassification

if TYPE_CHECKING:
    from app.models.match import MatchPackage


class PipelineResult(BaseModel):
    """
    Complete result of processing a single invoice through Stage 1.

    Contains every intermediate artifact for full auditability.
    """

    # --- Identity ---
    document_id: str = Field(description="Unique document identifier (UUID)")
    filename: str = Field(description="Original uploaded filename")

    # --- Status ---
    status: Literal[
        "stage1_passed",
        "needs_human_review",
        "extraction_failed"
    ] = Field(description="Final Stage 1 routing decision")

    # --- Timestamps ---
    upload_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the invoice was uploaded"
    )
    processing_time_seconds: float = Field(
        default=0.0,
        description="Total wall-clock processing time"
    )

    # --- Page Classification ---
    pages: list[PageClassification] = Field(
        default_factory=list,
        description="Page-level classification results"
    )

    # --- Extraction (LLM Call #1) ---
    extraction: InvoiceExtraction | None = Field(
        default=None,
        description="Structured extraction from primary LLM"
    )

    # --- Verification (LLM Call #2) ---
    verification: VerificationResult | None = Field(
        default=None,
        description="Independent verification result"
    )

    # --- Arithmetic Validation (legacy) ---
    arithmetic: ArithmeticResult | None = Field(
        default=None,
        description="Deterministic arithmetic check results (backward compatible)"
    )

    # --- Reconciliation ---
    reconciliation: ReconciliationResult | None = Field(
        default=None,
        description="Flexible reconciliation outcome"
    )

    evidence_profile: EvidenceProfile | None = Field(
        default=None,
        description="Structured extraction evidence for matching and validation"
    )
    extraction_quality: ExtractionQuality | None = Field(
        default=None,
        description="Extraction quality classification (metadata, not workflow gate)"
    )
    workflow_state: str = Field(
        default="",
        description="Explicit workflow state machine position"
    )

    # --- Decision ---
    decision: str = Field(
        default="",
        description="Short decision label (e.g., 'STAGE1_PASSED', 'NEEDS_HUMAN_REVIEW')"
    )
    decision_explanation: list[str] = Field(
        default_factory=list,
        description="Human-readable explanation of the routing decision"
    )

    # --- Error Handling ---
    retry_count: int = Field(default=0, description="Number of LLM retries performed")
    error_details: str | None = Field(
        default=None,
        description="Error information if processing failed"
    )

    # --- File Reference ---
    original_file_path: str = Field(
        default="",
        description="Path to the preserved original invoice file"
    )

    document_quality_score: float = Field(
        default=1.0,
        description="Pre-Stage 1 scan quality score (0.0–1.0)"
    )

    # --- Stage 2: PO Matching ---
    stage2_result: object | None = Field(
        default=None,
        description="Stage 2 MatchPackage result"
    )
    stage2_status: str = Field(
        default="",
        description="Stage 2 terminal match state"
    )

    # --- Stage 3: Validation ---
    stage3_result: object | None = Field(
        default=None,
        description="Stage 3 ValidationReport result"
    )
    stage3_status: str = Field(
        default="",
        description="Stage 3 overall validation state"
    )

    # --- Stage 4: Business Decision ---
    stage4_result: object | None = Field(
        default=None,
        description="Stage 4 DecisionRecord result"
    )
    stage4_status: str = Field(
        default="",
        description="Stage 4 decision substate"
    )
    stage4_decision: str = Field(
        default="",
        description="Stage 4 terminal decision (APPROVE/REVIEW_REQUIRED/REJECT/WAITING)"
    )

    # --- Stage 5: Explainability ---
    stage5_result: object | None = Field(
        default=None,
        description="Stage 5 ExplanationSnapshot result"
    )
    stage5_status: str = Field(
        default="",
        description="Stage 5 explanation status (COMPLETE/INCOMPLETE)"
    )
    stage5_explanation_id: str = Field(
        default="",
        description="Stage 5 explanation ID"
    )
