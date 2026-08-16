"""
InvoiceFlow AI — Stage 2: PO Presence Decision

Determines whether an invoice has a PO reference or should follow
the Non-PO workflow (GL Coding, Budget Approval, etc.).

No PO ≠ Failed Match — it's a different business workflow.
Non-PO invoices represent 30-50% of volume in many organizations.
"""

import logging

logger = logging.getLogger(__name__)


def check_po_presence(
    po_value: str | None,
    po_status: str,
) -> str:
    """
    Determine if this is a PO invoice or Non-PO invoice.

    Args:
        po_value: Extracted PO reference value.
        po_status: Extraction status.

    Returns:
        "po_invoice" or "non_po"
    """
    if po_value is None or po_status == "not_found":
        logger.info("PO presence: non_po (no PO reference found)")
        return "non_po"

    # Check if PO value looks valid (not empty/whitespace)
    cleaned = str(po_value).strip()
    if not cleaned or cleaned.lower() in ("n/a", "none", "null", "-"):
        logger.info(f"PO presence: non_po (PO value is '{cleaned}')")
        return "non_po"

    logger.info(f"PO presence: po_invoice (PO: {cleaned})")
    return "po_invoice"
