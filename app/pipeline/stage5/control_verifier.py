"""
InvoiceFlow AI — Stage 5: Control Verifier

PRD Section 4/22 — proves that required controls occurred.

A required control is NEVER shown as VERIFIED without an actual verification record.
Missing controls are PENDING or NO_RECORD_FOUND.
"""

import logging

from app.models.decision import DecisionRecord
from app.models.explanation import ControlVerification

logger = logging.getLogger(__name__)

# Substates that require specific control verification
CONTROL_REQUIREMENTS = {
    "APPROVAL_REQUIRED": {
        "control_type": "APPROVAL",
        "description": "Human approval required",
    },
    "VENDOR_SECURITY_REVIEW": {
        "control_type": "BANK_VERIFICATION",
        "description": "Vendor bank detail verification",
    },
    "FRAUD_REVIEW": {
        "control_type": "FRAUD_INVESTIGATION",
        "description": "Fraud investigation review",
    },
    "HIGH_PRIORITY_REVIEW": {
        "control_type": "SENIOR_REVIEW",
        "description": "Senior finance review",
    },
    "STANDARD_REVIEW": {
        "control_type": "AP_REVIEW",
        "description": "AP exception review",
    },
    "POLICY_EXCEPTION_REVIEW": {
        "control_type": "POLICY_REVIEW",
        "description": "Policy administrator review",
    },
}


def verify_controls(
    decision_record: DecisionRecord,
    human_actions: list | None = None,
) -> list[ControlVerification]:
    """
    Verify required controls based on decision substate.

    Returns:
        List of ControlVerification records. Missing controls
        are explicitly PENDING or NO_RECORD_FOUND.
    """
    verifications = []
    substate = decision_record.decision_substate

    # --- AUTO_APPROVED: no human control required ---
    if substate == "AUTO_APPROVED":
        verifications.append(ControlVerification(
            control_id=f"CV-{decision_record.decision_id}-AUTO",
            control_type="AUTO_APPROVAL",
            status="NOT_REQUIRED",
            verified_by="system",
            evidence="All validation controls passed; amount within auto-approval limit.",
        ))
        logger.info(f"[{decision_record.invoice_id}] Control: AUTO_APPROVED — no control required")
        return verifications

    # --- TERMINAL_REJECT: no control required ---
    if substate == "TERMINAL_REJECT":
        verifications.append(ControlVerification(
            control_id=f"CV-{decision_record.decision_id}-REJECT",
            control_type="TERMINAL_REJECT",
            status="NOT_REQUIRED",
            verified_by="system",
            evidence="Terminal rejection — no downstream control required.",
        ))
        return verifications

    # --- WAITING states: control is pending ---
    if substate in ("WAITING_FOR_GRN", "WAITING_FOR_REQUIRED_DATA",
                     "REVALIDATION_REQUIRED", "POLICY_CONFIGURATION_ERROR"):
        verifications.append(ControlVerification(
            control_id=f"CV-{decision_record.decision_id}-WAIT",
            control_type="DATA_RECEIPT",
            status="PENDING",
            gap_reason=f"Awaiting: {substate}",
        ))
        return verifications

    # --- Substates requiring specific control ---
    requirement = CONTROL_REQUIREMENTS.get(substate)
    if requirement:
        approved = _human_action_closes_control(human_actions, requirement["control_type"])
        status = "VERIFIED" if approved else "PENDING"
        gap = "" if approved else f"Required: {requirement['description']}. No verification record found."
        verifications.append(ControlVerification(
            control_id=f"CV-{decision_record.decision_id}-{requirement['control_type']}",
            control_type=requirement["control_type"],
            status=status,
            verified_by=approved.get("actor_id", "") if approved else "",
            verified_at=approved.get("timestamp", "") if approved else "",
            evidence=approved.get("detail", "") if approved else "",
            gap_reason=gap,
        ))

    # --- Dual control for CRITICAL tier ---
    if (decision_record.trace.authority.dual_control_required and
            substate == "APPROVAL_REQUIRED"):
        verifications.append(ControlVerification(
            control_id=f"CV-{decision_record.decision_id}-DUAL",
            control_type="DUAL_CONTROL",
            status="PENDING",
            gap_reason="Dual-control approval required for CRITICAL tier.",
        ))

    return verifications


def _human_action_closes_control(human_actions: list | None, control_type: str) -> dict | None:
    """Return approving human action if control is satisfied."""
    if not human_actions:
        return None
    closing_types = {"APPROVE", "OVERRIDE", "APPROVAL"}
    for action in human_actions:
        if isinstance(action, dict):
            action_type = action.get("action_type", "")
            outcome = action.get("outcome", "")
            data = action
        else:
            action_type = getattr(action, "action_type", "")
            outcome = getattr(action, "outcome", "")
            data = action.model_dump()
        if action_type in closing_types or outcome in closing_types:
            return data
    return None
