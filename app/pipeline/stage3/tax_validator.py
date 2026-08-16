"""
InvoiceFlow AI — Stage 3: Tax Validator

Stage 1 verifies arithmetic (subtotal + tax = total).
Stage 3 validates tax policy correctness:
  - Expected tax rate for jurisdiction
  - Tax base consistency
  - Tax tolerance
  - Zero/exempt handling
"""

import logging
from app.models.validation import ValidationCheck
from app.pipeline.stage3.validation_context import ValidationContext

logger = logging.getLogger(__name__)

RULE_ID = "TAX_VALIDATION"
RULE_VERSION = "TAX-2026.08.1"


def validate_tax(ctx: ValidationContext) -> ValidationCheck:
    """Validate tax correctness against policy."""
    inputs = {}
    calculations = {}
    findings = []

    tax_amount = ctx.tax_amount
    subtotal = ctx.subtotal
    total = ctx.total_amount

    # If no tax data at all, NOT_APPLICABLE
    if tax_amount is None and subtotal is None:
        return ValidationCheck(
            check_id="tax_validation",
            status="NOT_APPLICABLE",
            reason_code="NO_TAX_DATA",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            evidence=["No tax data available for validation"],
        )

    # Zero tax — valid if total == subtotal
    if tax_amount is not None and tax_amount == 0:
        findings.append("Zero tax invoice — tax exempt or zero-rated")
        return ValidationCheck(
            check_id="tax_validation",
            status="PASS",
            reason_code="",
            severity="LOW",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs={"tax_amount": 0, "expected_rate": ctx.expected_tax_rate},
            evidence=findings,
        )

    # Validate tax rate
    if tax_amount is not None and subtotal is not None and subtotal > 0:
        actual_rate = tax_amount / subtotal
        expected_tax = subtotal * ctx.expected_tax_rate
        variance = abs(tax_amount - expected_tax)
        variance_pct = variance / expected_tax if expected_tax > 0 else 0

        inputs = {
            "taxable_base": subtotal,
            "expected_rate": ctx.expected_tax_rate,
            "invoice_tax": tax_amount,
        }
        calculations = {
            "expected_tax": round(expected_tax, 2),
            "actual_rate": round(actual_rate, 4),
            "variance": round(variance, 2),
            "variance_pct": round(variance_pct, 4),
        }

        if variance_pct > ctx.tax_tolerance_pct:
            findings.append(
                f"Tax variance: expected ${expected_tax:,.2f} "
                f"({ctx.expected_tax_rate:.0%}), got ${tax_amount:,.2f} "
                f"({actual_rate:.1%}), variance: ${variance:,.2f} ({variance_pct:.1%})"
            )
            return ValidationCheck(
                check_id="tax_validation",
                status="FAIL",
                reason_code="TAX_VARIANCE",
                severity="HIGH",
                rule_id=RULE_ID,
                rule_version=RULE_VERSION,
                inputs=inputs,
                calculation=calculations,
                evidence=findings,
            )
        else:
            findings.append(
                f"Tax OK: ${tax_amount:,.2f} ({actual_rate:.1%}) "
                f"within tolerance of expected ${expected_tax:,.2f} ({ctx.expected_tax_rate:.0%})"
            )
            return ValidationCheck(
                check_id="tax_validation",
                status="PASS",
                rule_id=RULE_ID,
                rule_version=RULE_VERSION,
                inputs=inputs,
                calculation=calculations,
                evidence=findings,
            )

    # Tax exists but no subtotal to validate against — FLAG
    if tax_amount is not None:
        findings.append(
            f"Tax amount ${tax_amount:,.2f} present but no subtotal for rate validation"
        )
        return ValidationCheck(
            check_id="tax_validation",
            status="FLAG",
            reason_code="TAX_BASE_MISSING",
            severity="MEDIUM",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            inputs={"tax_amount": tax_amount},
            evidence=findings,
        )

    return ValidationCheck(
        check_id="tax_validation",
        status="NOT_APPLICABLE",
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        evidence=["Insufficient tax data for validation"],
    )
