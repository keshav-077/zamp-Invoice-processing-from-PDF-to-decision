"""
InvoiceFlow AI — Stage 2: Exception Manager

Ensures every invoice ends in a defined state.
Applies state transitions based on match signals.

States:
  MATCHED              — Score ≥ 95, no ambiguity
  HIGH_CONFIDENCE_MATCH — Score 70–95, clear winner
  AMBIGUOUS_MATCH      — Gap < 5 between top candidates
  PARTIAL_MATCH        — Some lines matched, others not
  NON_PO_WORKFLOW      — No PO reference on invoice
  WAITING_FOR_PO       — PO not found in system
  WAITING_FOR_GRN      — PO matched but no receipt
  CLOSED_PO_REVIEW     — Matched PO is closed/cancelled
  UNMATCHED            — Score < 70, no viable candidate
"""

import logging

logger = logging.getLogger(__name__)


class ExceptionManager:
    """Manages Stage 2 exception states and routing."""

    def determine_final_state(
        self,
        ambiguity_status: str,
        unmatched_lines: list[int],
        total_lines: int,
        po_validation_flags: list[str],
        balance_flags: list[str],
        has_grn: bool,
        po_type: str = "standard",
        grn_required_types: list[str] | None = None,
    ) -> tuple[str, list[str]]:
        """
        Determine the final Stage 2 state and flags.

        Args:
            ambiguity_status: Status from ambiguity detector.
            unmatched_lines: Invoice lines with no PO match.
            total_lines: Total number of invoice lines.
            po_validation_flags: Flags from PO status validation.
            balance_flags: Flags from balance tracker.
            has_grn: Whether GRN records exist for matched PO(s).

        Returns:
            (final_status, exception_flags)
        """
        flags = []

        # Check PO status exceptions first
        if "cancelled_po" in po_validation_flags:
            flags.append("cancelled_po_exception")
            logger.info("Exception: cancelled PO → CLOSED_PO_REVIEW")
            return "closed_po_review", flags

        if "closed_po" in po_validation_flags:
            flags.append("closed_po_exception")
            logger.info("Exception: closed PO → CLOSED_PO_REVIEW")
            return "closed_po_review", flags

        # GRN check — only standard/goods POs require receipt confirmation
        require_grn_types = grn_required_types or ["standard"]
        header_only_match = total_lines == 0 and ambiguity_status in (
            "matched",
            "high_confidence_match",
        )
        if (
            not has_grn
            and ambiguity_status in ("matched", "high_confidence_match")
            and po_type in require_grn_types
            and not header_only_match
        ):
            flags.append("no_grn_record")
            logger.info("Exception: no GRN for %s PO → WAITING_FOR_GRN", po_type)
            return "waiting_for_grn", flags
        elif not has_grn and po_type not in require_grn_types:
            logger.info("GRN not required for %s PO — continuing without receipt", po_type)

        # Check partial match
        if unmatched_lines and total_lines > 0:
            matched_ratio = (total_lines - len(unmatched_lines)) / total_lines
            if matched_ratio > 0 and matched_ratio < 1.0:
                flags.append(f"partial_match_{len(unmatched_lines)}_unmatched")
                # If mostly matched, keep the base status but add partial flag
                if matched_ratio >= 0.5:
                    flags.append("partial_invoice")
                    logger.info(
                        f"Exception: partial match ({matched_ratio:.0%} matched) "
                        f"— PARTIAL_MATCH"
                    )
                    return "partial_match", flags
                else:
                    # Less than half matched — treat as unmatched
                    logger.info(
                        f"Exception: low partial match ({matched_ratio:.0%}) — UNMATCHED"
                    )
                    return "unmatched", flags

        # Check balance flags
        if "potential_overbilling" in balance_flags:
            flags.append("overbilling_warning")

        # Use ambiguity status as the base
        logger.info(f"Final state: {ambiguity_status} (flags: {flags})")
        return ambiguity_status, flags
