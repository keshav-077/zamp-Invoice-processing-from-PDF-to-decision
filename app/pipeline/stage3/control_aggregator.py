"""
InvoiceFlow AI — Stage 3: Control & Aggregation Policy Engine

Implements the canonical decision tree (PRD Section 36):
  BLOCKED              ← hard blocking control
  HOLD                 ← hard financial/business failure
  VALIDATION_INCOMPLETE← required check UNAVAILABLE
  REVIEW_REQUIRED      ← review-level findings
  VALIDATED            ← all applicable checks PASS

Critical rule: 6 PASS results cannot cancel 1 critical FAIL.
Uses control PRECEDENCE, not majority voting.
"""

import logging
from app.models.validation import (
    ValidationCheck, ControlRecord, FraudSignal, OverallState
)

logger = logging.getLogger(__name__)


# Reason codes that trigger BLOCK (highest precedence)
BLOCKING_REASONS = {
    "DUPLICATE_CONFIRMED",
    "VENDOR_BLACKLISTED",
}

# Reason codes that trigger HOLD
HOLD_REASONS = {
    "PRICE_VARIANCE_EXCEEDED",
    "BUDGET_EXCEEDED",
    "TAX_VARIANCE",
    "VENDOR_INELIGIBLE",
    "GRN_MISSING",
}

# Statuses that mean "check couldn't complete"
UNAVAILABLE_STATUSES = {"UNAVAILABLE"}

# Statuses that mean "review needed"
FLAG_STATUSES = {"FLAG"}

# Statuses that pass
PASS_STATUSES = {"PASS", "NOT_APPLICABLE"}


def aggregate_controls(
    checks: dict[str, ValidationCheck],
    fraud_signals: list[FraudSignal],
    match_status: str,
) -> tuple[OverallState, list[str], list[ControlRecord]]:
    """
    Apply control precedence policy to determine overall validation state.

    Args:
        checks: All validation check results by check_id
        fraud_signals: Fraud signals from fraud detector
        match_status: Stage 2 match status (affects routing)

    Returns:
        (overall_state, reason_codes, controls)
    """
    reason_codes = []
    controls = []

    # Collect check results by category
    blocking = []
    holding = []
    unavailable = []
    flagging = []
    passing = []

    for check_id, check in checks.items():
        if check.reason_code in BLOCKING_REASONS:
            blocking.append(check)
        elif check.status == "FAIL":
            if check.reason_code in HOLD_REASONS:
                holding.append(check)
            else:
                holding.append(check)  # Any FAIL is at least a HOLD
        elif check.status in UNAVAILABLE_STATUSES:
            unavailable.append(check)
        elif check.status in FLAG_STATUSES:
            flagging.append(check)
        elif check.status in PASS_STATUSES:
            passing.append(check)

    # Check high-severity fraud signals
    high_fraud = [s for s in fraud_signals if s.severity in ("HIGH", "CRITICAL")]
    medium_fraud = [s for s in fraud_signals if s.severity == "MEDIUM"]

    # --- Apply precedence tree (PRD Section 36) ---

    # 1. Hard blocking control?
    if blocking:
        for check in blocking:
            reason_codes.append(check.reason_code)
            controls.append(ControlRecord(
                control_type="BLOCK",
                reason_code=check.reason_code,
                check_id=check.check_id,
                detail="; ".join(check.evidence[:2]),
            ))
        logger.info(f"Control aggregation: BLOCKED ({reason_codes})")
        return "BLOCKED", reason_codes, controls

    # 2. Hard financial/business failure?
    if holding:
        for check in holding:
            reason_codes.append(check.reason_code)
            controls.append(ControlRecord(
                control_type="HOLD",
                reason_code=check.reason_code,
                check_id=check.check_id,
                detail="; ".join(check.evidence[:2]),
            ))
        logger.info(f"Control aggregation: HOLD ({reason_codes})")
        return "HOLD", reason_codes, controls

    # 3. Required check unavailable?
    if unavailable:
        for check in unavailable:
            reason_codes.append(check.reason_code)
        logger.info(f"Control aggregation: VALIDATION_INCOMPLETE ({reason_codes})")
        return "VALIDATION_INCOMPLETE", reason_codes, controls

    # 4. Review-level findings?
    if flagging or high_fraud or medium_fraud:
        for check in flagging:
            reason_codes.append(check.reason_code)
        for sig in high_fraud + medium_fraud:
            reason_codes.append(sig.signal_type)
        # Ambiguous Stage 2 match also forces review
        if match_status == "ambiguous_match":
            reason_codes.append("AMBIGUOUS_PO_MATCH")
        logger.info(f"Control aggregation: REVIEW_REQUIRED ({reason_codes})")
        return "REVIEW_REQUIRED", reason_codes, controls

    # 5. Ambiguous match forces review even without findings
    if match_status == "ambiguous_match":
        reason_codes.append("AMBIGUOUS_PO_MATCH")
        logger.info("Control aggregation: REVIEW_REQUIRED (ambiguous match)")
        return "REVIEW_REQUIRED", reason_codes, controls

    # 6. All applicable checks pass
    logger.info("Control aggregation: VALIDATED")
    return "VALIDATED", reason_codes, controls
