"""
InvoiceFlow AI — Stage 4: Decision Context Builder

Builds the canonical decision context from Stage 3 ValidationReport
plus financial, vendor, and authority context.
"""

import logging
import uuid
from dataclasses import dataclass, field

from app.models.validation import ValidationReport

logger = logging.getLogger(__name__)


@dataclass
class DecisionContext:
    """Canonical decision context for Stage 4 evaluation."""

    # --- Identity ---
    decision_request_id: str = ""
    invoice_id: str = ""
    validation_run_id: str = ""

    # --- Stage 3 state ---
    validation_state: str = ""
    validation_processing_state: str = ""
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    controls: list[dict] = field(default_factory=list)
    fraud_signals: list[dict] = field(default_factory=list)
    check_statuses: dict[str, str] = field(default_factory=dict)

    # --- Financial ---
    amount: float | None = None
    currency: str | None = None
    matched_po_number: str | None = None

    # --- Vendor risk ---
    vendor_id: str | None = None
    vendor_status: str = ""
    vendor_risk_tier: str = "STANDARD"
    is_first_payment: bool = False
    bank_change_detected: bool = False
    bank_change_verified: bool = False

    # --- Policy inputs ---
    policy_version: str = ""
    source_snapshots: dict = field(default_factory=dict)
    validated_at: str = ""

    # --- Evidence summary ---
    evidence_summary: list[str] = field(default_factory=list)


def build_decision_context(
    validation_report: ValidationReport,
) -> DecisionContext:
    """
    Build a decision context from Stage 3 ValidationReport.

    Args:
        validation_report: The Stage 3 output

    Returns:
        DecisionContext with all data needed for the 10-step decision pipeline.
    """
    ctx = DecisionContext(
        decision_request_id=f"DR-{uuid.uuid4().hex[:12].upper()}",
        invoice_id=validation_report.invoice_id,
        validation_run_id=validation_report.validation_run_id,
    )

    # --- Stage 3 state ---
    ctx.validation_state = validation_report.overall_state
    ctx.validation_processing_state = validation_report.processing_state
    ctx.reason_codes = list(validation_report.reason_codes)
    ctx.evidence_refs = []  # Collect from checks
    ctx.controls = [c.model_dump() for c in validation_report.controls]
    ctx.fraud_signals = [s.model_dump() for s in validation_report.fraud_signals]
    ctx.evidence_summary = list(validation_report.evidence_summary)

    # Collect check statuses
    for check_id, check in validation_report.checks.items():
        ctx.check_statuses[check_id] = check.status
        ctx.evidence_refs.extend(check.evidence_refs)

    # --- Financial (from checks inputs if available) ---
    for check_id, check in validation_report.checks.items():
        if check.inputs.get("invoice_total"):
            ctx.amount = check.inputs["invoice_total"]
            break
        if check.inputs.get("total_amount"):
            ctx.amount = check.inputs["total_amount"]
            break

    # --- Vendor context (from vendor validation check) ---
    vendor_check = validation_report.checks.get("vendor_validation")
    if vendor_check:
        ctx.vendor_id = vendor_check.inputs.get("vendor_id")
        ctx.vendor_status = vendor_check.inputs.get("vendor_status", "")

    # --- Fraud signals → bank change / new vendor detection ---
    for signal in validation_report.fraud_signals:
        if signal.signal_type == "NEW_VENDOR_HIGH_AMOUNT":
            ctx.is_first_payment = True
        # Bank change would come from vendor validation evidence
    for control in validation_report.controls:
        if "bank" in control.reason_code.lower():
            ctx.bank_change_detected = True

    # --- Policy & snapshots ---
    ctx.policy_version = validation_report.policy_version
    ctx.source_snapshots = validation_report.source_snapshots.model_dump()
    ctx.validated_at = validation_report.completed_at
    po_ref = ctx.source_snapshots.get("po") or ""
    if po_ref:
        ctx.matched_po_number = po_ref.split(":")[0]

    logger.info(
        f"[{ctx.invoice_id}] Decision context built: "
        f"state={ctx.validation_state}, amount={ctx.amount}, "
        f"vendor={ctx.vendor_id}"
    )
    return ctx
