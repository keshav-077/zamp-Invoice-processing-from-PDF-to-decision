"""
InvoiceFlow AI — Stage 2: PO Status Validator

Validates PO eligibility for matching:
- PO exists?
- PO is open/active?
- PO is not expired?
- PO is not cancelled?
- Handles closed PO scenarios (soft vs hard close)
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class POValidationResult:
    """Result of PO status validation."""
    def __init__(self, is_valid: bool, status: str, reason: str, flags: list[str] = None):
        self.is_valid = is_valid
        self.status = status
        self.reason = reason
        self.flags = flags or []


class POValidator:
    """Validates PO status and eligibility for matching."""

    def validate(self, po: dict) -> POValidationResult:
        """
        Validate a PO's eligibility.

        Args:
            po: PO dict from database with status, expiry_date, etc.

        Returns:
            POValidationResult with validity and routing info.
        """
        po_number = po.get("po_number", "?")
        status = po.get("status", "unknown")
        po_type = po.get("po_type", "standard")

        # Check PO status
        if status == "open":
            # Check expiry
            expiry = po.get("expiry_date")
            if expiry:
                try:
                    expiry_date = datetime.strptime(expiry, "%Y-%m-%d")
                    if expiry_date < datetime.now():
                        logger.info(f"PO {po_number}: expired ({expiry})")
                        return POValidationResult(
                            is_valid=False,
                            status="expired",
                            reason=f"PO {po_number} expired on {expiry}",
                            flags=["expired_po"],
                        )
                except ValueError:
                    pass  # Can't parse date, skip expiry check

            logger.info(f"PO {po_number}: valid (open, {po_type})")
            return POValidationResult(
                is_valid=True,
                status="open",
                reason=f"PO {po_number} is open and active",
            )

        elif status == "closed_for_invoicing":
            # Soft close — route to review, don't reject
            logger.info(f"PO {po_number}: closed_for_invoicing → review")
            return POValidationResult(
                is_valid=False,
                status="closed_for_invoicing",
                reason=f"PO {po_number} is closed for invoicing — requires review",
                flags=["closed_po", "review_required"],
            )

        elif status == "closed":
            # Hard close — needs review
            logger.info(f"PO {po_number}: closed → review")
            return POValidationResult(
                is_valid=False,
                status="closed",
                reason=f"PO {po_number} is closed",
                flags=["closed_po", "review_required"],
            )

        elif status == "cancelled":
            # Cancelled — escalate
            logger.info(f"PO {po_number}: cancelled → escalate")
            return POValidationResult(
                is_valid=False,
                status="cancelled",
                reason=f"PO {po_number} is cancelled — cannot match",
                flags=["cancelled_po", "escalation_required"],
            )

        else:
            logger.warning(f"PO {po_number}: unknown status '{status}'")
            return POValidationResult(
                is_valid=False,
                status="unknown",
                reason=f"PO {po_number} has unknown status: {status}",
                flags=["unknown_status"],
            )
