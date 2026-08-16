"""
InvoiceFlow AI — Stage 3: Budget & Tolerance Validator

Validates PO and budget availability:
  - PO remaining balance vs invoice amount
  - Budget tolerance (configurable overage %)
  - Cumulative tracking (previously invoiced + current)

Uses atomic-safe semantics: does not modify shared state.
"""

import logging
from app.models.validation import ValidationCheck
from app.pipeline.stage3.validation_context import ValidationContext

logger = logging.getLogger(__name__)

RULE_ID = "BUDGET_TOLERANCE"
RULE_VERSION = "BUD-2026.08.1"


def validate_budget(ctx: ValidationContext) -> ValidationCheck:
    """Validate invoice fits within PO balance and budget tolerance."""
    if ctx.po is None:
        return ValidationCheck(
            check_id="budget_tolerance",
            status="NOT_APPLICABLE",
            reason_code="NO_PO_CONTEXT",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            evidence=["No PO context — budget validation not applicable"],
        )

    if ctx.total_amount is None:
        return ValidationCheck(
            check_id="budget_tolerance",
            status="UNAVAILABLE",
            reason_code="NO_INVOICE_TOTAL",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            evidence=["Invoice total not available for budget validation"],
        )

    findings = []
    inputs = {
        "invoice_total": ctx.total_amount,
        "po_total": ctx.po_total,
        "previously_invoiced": ctx.po_previously_invoiced,
        "po_remaining": ctx.po_remaining,
        "tolerance_pct": ctx.budget_tolerance_pct,
    }
    calculations = {}

    # --- PO Remaining Balance Check ---
    remaining = ctx.po_remaining
    tolerance_amount = ctx.po_total * ctx.budget_tolerance_pct
    effective_limit = remaining + tolerance_amount

    cumulative = ctx.po_previously_invoiced + ctx.total_amount
    utilization = cumulative / ctx.po_total if ctx.po_total > 0 else 0

    calculations["effective_limit"] = round(effective_limit, 2)
    calculations["cumulative_invoiced"] = round(cumulative, 2)
    calculations["utilization_pct"] = round(utilization, 4)
    calculations["tolerance_amount"] = round(tolerance_amount, 2)

    if ctx.total_amount <= remaining:
        # Within remaining balance — PASS
        findings.append(
            f"Budget OK: ${ctx.total_amount:,.2f} within remaining "
            f"${remaining:,.2f} (utilization: {utilization:.0%})"
        )
        return ValidationCheck(
            check_id="budget_tolerance",
            status="PASS",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            calculation=calculations,
            evidence=findings,
            evidence_refs=[ctx.po_ref] if ctx.po_ref else [],
        )

    elif ctx.total_amount <= effective_limit:
        # Within tolerance — FLAG
        overage = ctx.total_amount - remaining
        findings.append(
            f"Budget tolerance: ${ctx.total_amount:,.2f} exceeds remaining "
            f"${remaining:,.2f} by ${overage:,.2f} but within "
            f"{ctx.budget_tolerance_pct:.0%} tolerance "
            f"(effective limit: ${effective_limit:,.2f})"
        )
        return ValidationCheck(
            check_id="budget_tolerance",
            status="FLAG",
            reason_code="BUDGET_TOLERANCE_USED",
            severity="MEDIUM",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            calculation=calculations,
            evidence=findings,
            evidence_refs=[ctx.po_ref] if ctx.po_ref else [],
        )

    else:
        # Exceeds tolerance — FAIL
        overage = ctx.total_amount - remaining
        findings.append(
            f"BUDGET EXCEEDED: ${ctx.total_amount:,.2f} exceeds remaining "
            f"${remaining:,.2f} by ${overage:,.2f} — beyond "
            f"{ctx.budget_tolerance_pct:.0%} tolerance "
            f"(effective limit: ${effective_limit:,.2f}, "
            f"cumulative: ${cumulative:,.2f} of ${ctx.po_total:,.2f})"
        )
        return ValidationCheck(
            check_id="budget_tolerance",
            status="FAIL",
            reason_code="BUDGET_EXCEEDED",
            severity="HIGH",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs=inputs,
            calculation=calculations,
            evidence=findings,
            evidence_refs=[ctx.po_ref] if ctx.po_ref else [],
        )
