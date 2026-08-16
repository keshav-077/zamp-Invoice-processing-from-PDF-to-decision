"""
InvoiceFlow AI — Stage 2: PO Balance Tracker

Tracks cumulative PO usage to prevent over-billing:
  remaining = total_amount - previously_invoiced

Flags if current invoice would exceed remaining balance.
Does NOT reject — that's Stage 3/4's job.
"""

import logging

logger = logging.getLogger(__name__)


class BalanceCheck:
    """Result of balance validation."""
    def __init__(
        self,
        remaining: float,
        invoice_amount: float,
        is_within_balance: bool,
        flags: list[str] = None,
        detail: str = "",
    ):
        self.remaining = remaining
        self.invoice_amount = invoice_amount
        self.is_within_balance = is_within_balance
        self.flags = flags or []
        self.detail = detail


class BalanceTracker:
    """Tracks PO balance and flags potential overbilling."""

    def check_balance(
        self,
        po: dict,
        invoice_total: float | None,
        line_mappings: list | None = None,
    ) -> BalanceCheck:
        """
        Check if invoice amount fits within PO remaining balance.

        Args:
            po: PO dict with total_amount, previously_invoiced.
            invoice_total: Total amount from the current invoice.

        Returns:
            BalanceCheck with remaining balance and flags.
        """
        po_number = po.get("po_number", "?")
        total_amount = po.get("total_amount", 0)
        previously_invoiced = po.get("previously_invoiced", 0)
        remaining = total_amount - previously_invoiced

        line_flags: list[str] = []
        if line_mappings and po.get("lines"):
            po_line_map = {l["line_number"]: l for l in po["lines"]}
            for mapping in line_mappings:
                if mapping.match_type == "unmatched":
                    continue
                po_line = po_line_map.get(mapping.po_line)
                if not po_line:
                    continue
                qty = po_line.get("quantity", 0)
                invoiced_qty = po_line.get("invoiced_quantity", 0)
                remaining_qty = qty - invoiced_qty
                inv_line_qty = None
                if hasattr(mapping, "allocated_quantity"):
                    inv_line_qty = mapping.allocated_quantity
                if inv_line_qty is not None and inv_line_qty > remaining_qty + 1e-6:
                    line_flags.append(
                        f"line_{mapping.po_line}_qty_exceeded"
                    )

        if invoice_total is None:
            return BalanceCheck(
                remaining=remaining,
                invoice_amount=0,
                is_within_balance=True,
                flags=line_flags,
                detail=f"PO {po_number}: remaining ${remaining:,.2f} (invoice total unknown)",
            )

        is_within = invoice_total <= remaining

        if is_within:
            detail = (
                f"PO {po_number}: ${invoice_total:,.2f} of ${remaining:,.2f} remaining "
                f"(total: ${total_amount:,.2f}, prior: ${previously_invoiced:,.2f})"
            )
            logger.info(f"Balance OK: {detail}")
            return BalanceCheck(
                remaining=remaining,
                invoice_amount=invoice_total,
                is_within_balance=True,
                flags=line_flags,
                detail=detail,
            )
        else:
            overage = invoice_total - remaining
            detail = (
                f"PO {po_number}: invoice ${invoice_total:,.2f} exceeds remaining "
                f"${remaining:,.2f} by ${overage:,.2f} "
                f"(total: ${total_amount:,.2f}, prior: ${previously_invoiced:,.2f})"
            )
            logger.warning(f"Balance exceeded: {detail}")
            flags = ["potential_overbilling", f"overage_{overage:.2f}"] + line_flags
            return BalanceCheck(
                remaining=remaining,
                invoice_amount=invoice_total,
                is_within_balance=False,
                flags=flags,
                detail=detail,
            )
