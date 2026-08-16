"""
InvoiceFlow AI — Stage 2: Extraction Confidence Gate

Evaluates PO reference confidence from Stage 1 extraction to determine
how aggressively to search for PO candidates.

Thresholds:
  > 0.90  →  trust    (direct lookup)
  0.70–0.90 →  validate (lookup + secondary signals)
  < 0.70  →  expand   (fuzzy search + vendor-based discovery)
"""

import logging

logger = logging.getLogger(__name__)

# Confidence thresholds
TRUST_THRESHOLD = 0.90
VALIDATE_THRESHOLD = 0.70


def evaluate_confidence(
    po_value: str | None,
    po_confidence: float,
    po_status: str,
) -> str:
    """
    Determine the confidence gate action.

    Args:
        po_value: Extracted PO reference value (may be None).
        po_confidence: Confidence score for PO extraction.
        po_status: Extraction status (extracted, inferred, not_found, uncertain).

    Returns:
        One of: "trust", "validate", "expand"
    """
    # If no PO extracted at all, expand search
    if po_value is None or po_status == "not_found":
        logger.info("Confidence gate: NO PO → expand")
        return "expand"

    # If uncertain status, always validate regardless of confidence
    if po_status == "uncertain":
        logger.info(f"Confidence gate: uncertain status → validate (confidence: {po_confidence:.2f})")
        return "validate"

    # Confidence-based routing
    if po_confidence >= TRUST_THRESHOLD:
        action = "trust"
    elif po_confidence >= VALIDATE_THRESHOLD:
        action = "validate"
    else:
        action = "expand"

    logger.info(
        f"Confidence gate: {action} "
        f"(confidence: {po_confidence:.2f}, value: {po_value})"
    )
    return action
