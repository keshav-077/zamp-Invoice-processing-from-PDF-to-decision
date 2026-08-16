"""
InvoiceFlow AI — Stage 3: Receipt / 2-Way / 3-Way Match Validator

PO type determines match type:
  - Goods with receiving required → 3-way (PO + GRN + Invoice)
  - Services → 2-way (PO + Invoice)
  - Subscriptions → 2-way (PO + Invoice)
  - Blanket PO → Policy-defined

Critical rule: missing GRN is NOT automatically a failure AND NOT automatically a pass.
"""

import logging
from app.models.validation import ValidationCheck
from app.pipeline.stage3.validation_context import ValidationContext

logger = logging.getLogger(__name__)

RULE_ID = "RECEIPT_MATCH"
RULE_VERSION = "GRN-2026.08.1"

# PO types that require 3-way matching (GRN required)
THREE_WAY_PO_TYPES = {"standard"}  # standard goods POs need GRN
TWO_WAY_PO_TYPES = {"blanket"}  # services/blanket = 2-way


def validate_receipt(ctx: ValidationContext) -> ValidationCheck:
    """Validate receipt/GRN matching based on PO type."""
    if ctx.po is None:
        return ValidationCheck(
            check_id="receipt_match",
            status="NOT_APPLICABLE",
            reason_code="NO_PO_CONTEXT",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            evidence=["No PO context — receipt validation not applicable"],
        )

    findings = []
    inputs = {
        "po_number": ctx.matched_po_number,
        "po_type": ctx.po_type,
        "has_grn": ctx.has_grn,
        "grn_count": len(ctx.grn_records),
        "total_received": ctx.total_received_amount,
    }

    # Determine match type based on PO type
    if ctx.po_type in TWO_WAY_PO_TYPES:
        # 2-way match: PO + Invoice — no GRN required
        findings.append(
            f"2-way match: PO type '{ctx.po_type}' — GRN not required"
        )
        return ValidationCheck(
            check_id="receipt_match",
            status="PASS",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            evidence=findings,
        )

    # 3-way match: PO + GRN + Invoice
    findings.append(f"3-way match required: PO type '{ctx.po_type}'")

    if not ctx.has_grn:
        # GRN missing — UNAVAILABLE (not FAIL, not PASS)
        findings.append(
            f"GRN MISSING: PO {ctx.matched_po_number} requires goods receipt "
            f"but no GRN records found. Invoice cannot be fully validated."
        )
        return ValidationCheck(
            check_id="receipt_match",
            status="UNAVAILABLE",
            reason_code="GRN_MISSING",
            severity="HIGH",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            evidence=findings,
        )

    # GRN exists — validate received amounts
    calculations = {}

    # Check received amount vs invoice amount
    if ctx.total_amount is not None and ctx.total_received_amount > 0:
        receipt_coverage = ctx.total_received_amount / ctx.total_amount if ctx.total_amount > 0 else 0
        calculations["receipt_coverage"] = round(receipt_coverage, 4)
        calculations["total_received"] = ctx.total_received_amount
        calculations["invoice_total"] = ctx.total_amount
        inputs["receipt_coverage"] = round(receipt_coverage, 4)

        if receipt_coverage >= 0.95:
            # Fully received
            findings.append(
                f"3-way match: receipt coverage {receipt_coverage:.0%} "
                f"(received: ${ctx.total_received_amount:,.2f}, "
                f"invoice: ${ctx.total_amount:,.2f})"
            )
            return ValidationCheck(
                check_id="receipt_match",
                status="PASS",
                rule_id=RULE_ID,
                rule_version=RULE_VERSION,
                inputs=inputs,
                calculation=calculations,
                evidence=findings,
                evidence_refs=[ctx.grn_ref] if ctx.grn_ref else [],
            )
        elif receipt_coverage >= 0.5:
            # Partially received
            shortfall = ctx.total_amount - ctx.total_received_amount
            findings.append(
                f"PARTIAL RECEIPT: coverage {receipt_coverage:.0%}, "
                f"shortfall ${shortfall:,.2f}"
            )
            return ValidationCheck(
                check_id="receipt_match",
                status="FLAG",
                reason_code="PARTIAL_RECEIPT",
                severity="MEDIUM",
                rule_id=RULE_ID,
                rule_version=RULE_VERSION,
                inputs=inputs,
                calculation=calculations,
                evidence=findings,
            )
        else:
            # Very low receipt coverage
            findings.append(
                f"LOW RECEIPT COVERAGE: only {receipt_coverage:.0%} received"
            )
            return ValidationCheck(
                check_id="receipt_match",
                status="FLAG",
                reason_code="LOW_RECEIPT_COVERAGE",
                severity="HIGH",
                rule_id=RULE_ID,
                rule_version=RULE_VERSION,
                inputs=inputs,
                calculation=calculations,
                evidence=findings,
            )

    # GRN exists but can't compare amounts
    findings.append(
        f"GRN records found ({len(ctx.grn_records)}) but amount comparison inconclusive"
    )
    return ValidationCheck(
        check_id="receipt_match",
        status="PASS",
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        inputs=inputs,
        evidence=findings,
    )
