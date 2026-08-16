"""
InvoiceFlow AI — Stage 3: Contract & Integrity Gate
"""

import logging

from app.models.match import MatchPackage, MATCH_STATES

logger = logging.getLogger(__name__)

FULL_VALIDATION_STATES = {
    "matched",
    "high_confidence_match",
    "partial_match",
    "ambiguous_match",
    "waiting_for_grn",
    "closed_po_review",
}

LIMITED_VALIDATION_STATES = {
    "non_po_workflow",
}

NO_VALIDATION_STATES = {
    "waiting_for_po",
    "suggested_po_match",
    "unmatched",
    "multiple_candidates",
}

EVIDENCE_PROVENANCE = {"evidence", "authoritative_po", "human_confirmed"}


class ContractGateResult:
    def __init__(
        self,
        is_valid: bool,
        validation_mode: str,
        reason: str = "",
        engines_to_run: list[str] | None = None,
    ):
        self.is_valid = is_valid
        self.validation_mode = validation_mode
        self.reason = reason
        self.engines_to_run = engines_to_run or []


def validate_contract(
    invoice_id: str,
    match_package: MatchPackage,
) -> ContractGateResult:
    if not invoice_id:
        return ContractGateResult(is_valid=False, validation_mode="none", reason="Missing invoice ID")

    if not match_package:
        return ContractGateResult(is_valid=False, validation_mode="none", reason="Missing match package")

    match_status = match_package.match_status

    if match_status not in MATCH_STATES:
        logger.warning("Unknown match status: %s", match_status)
        return ContractGateResult(
            is_valid=False,
            validation_mode="none",
            reason=f"Unknown match status: {match_status}",
        )

    # Suggestion-only matches without selected PO cannot run full validation
    if (
        match_package.suggestion_mode
        and match_status in NO_VALIDATION_STATES
        and not match_package.matched_pos
    ):
        return ContractGateResult(
            is_valid=True,
            validation_mode="none",
            reason=f"Stage 2 state '{match_status}' — awaiting PO confirmation",
        )

    if match_status in FULL_VALIDATION_STATES:
        if (
            match_package.suggestion_mode
            and match_package.match_provenance not in EVIDENCE_PROVENANCE
        ):
            return ContractGateResult(
                is_valid=True,
                validation_mode="none",
                reason="Suggestion mode — PO not confirmed",
            )
        if match_status == "ambiguous_match" and match_package.match_provenance != "human_confirmed":
            return ContractGateResult(
                is_valid=True,
                validation_mode="none",
                reason="Ambiguous PO match — human confirmation required",
            )

        engines = [
            "amount_variance",
            "tax_validation",
            "duplicate_detection",
            "vendor_validation",
            "receipt_match",
            "budget_tolerance",
            "fraud_signals",
        ]
        logger.info("Contract gate: FULL validation (%s, provenance=%s)", match_status, match_package.match_provenance)
        return ContractGateResult(is_valid=True, validation_mode="full", engines_to_run=engines)

    if match_status in LIMITED_VALIDATION_STATES:
        engines = ["duplicate_detection", "vendor_validation", "fraud_signals"]
        logger.info("Contract gate: LIMITED validation (%s)", match_status)
        return ContractGateResult(is_valid=True, validation_mode="limited", engines_to_run=engines)

    if match_status in NO_VALIDATION_STATES:
        logger.info("Contract gate: NO validation (%s)", match_status)
        return ContractGateResult(
            is_valid=True,
            validation_mode="none",
            reason=f"Stage 2 state '{match_status}' — validation cannot proceed",
        )

    return ContractGateResult(
        is_valid=False,
        validation_mode="none",
        reason=f"Unhandled match status: {match_status}",
    )
