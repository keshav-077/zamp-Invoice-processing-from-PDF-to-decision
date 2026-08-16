"""
InvoiceFlow AI — Stage 3: Amount & Price Variance Validator

Validates invoice financial alignment against the matched PO at line and header level.
Stage 1 checked internal arithmetic; Stage 3 checks commercial alignment.

Checks:
  1. Unit price variance (per line)
  2. Quantity variance (per line)
  3. Line amount consistency
  4. Header total alignment
  5. PO remaining balance
"""

import logging
from app.models.validation import ValidationCheck
from app.pipeline.stage3.validation_context import ValidationContext

logger = logging.getLogger(__name__)

RULE_ID = "AMOUNT_VARIANCE"
RULE_VERSION = "AMT-2026.08.1"


def validate_amount(ctx: ValidationContext) -> ValidationCheck:
    """
    Validate invoice amount/price alignment against matched PO.

    Returns:
        ValidationCheck with status and evidence.
    """
    if ctx.po is None:
        return ValidationCheck(
            check_id="amount_variance",
            status="NOT_APPLICABLE",
            reason_code="NO_PO_CONTEXT",
            rule_id=RULE_ID,
            rule_version=RULE_VERSION,
            evidence=["No PO context available for amount validation"],
        )

    findings = []
    has_failure = False
    has_flag = False
    inputs = {}
    calculations = {}

    # --- 1. Unit Price Variance (per matched line) ---
    for mapping in ctx.line_mappings:
        if mapping.get("match_type") == "unmatched":
            continue

        inv_line_num = mapping.get("invoice_line", 0)
        po_line_num = mapping.get("po_line", 0)

        # Find corresponding lines
        inv_line = _get_invoice_line(ctx.invoice_lines, inv_line_num)
        po_line = _get_po_line(ctx.po_lines, po_line_num)

        if inv_line and po_line:
            inv_price = inv_line.get("unit_price")
            po_price = po_line.get("unit_price")

            if inv_price is not None and po_price is not None and po_price > 0:
                variance_pct = abs(inv_price - po_price) / po_price
                variance_amt = abs(inv_price - po_price)

                if variance_pct > ctx.price_tolerance_pct:
                    has_failure = True
                    findings.append(
                        f"Line {inv_line_num}: price variance {variance_pct:.1%} "
                        f"(inv: ${inv_price:,.2f} vs PO: ${po_price:,.2f}, "
                        f"tolerance: {ctx.price_tolerance_pct:.0%})"
                    )
                else:
                    findings.append(
                        f"Line {inv_line_num}: price OK "
                        f"(variance: {variance_pct:.1%} within {ctx.price_tolerance_pct:.0%})"
                    )

                calculations[f"line_{inv_line_num}_price_variance"] = {
                    "invoice_price": inv_price,
                    "po_price": po_price,
                    "variance_pct": round(variance_pct, 4),
                    "variance_amt": round(variance_amt, 2),
                    "tolerance_pct": ctx.price_tolerance_pct,
                    "status": "FAIL" if variance_pct > ctx.price_tolerance_pct else "PASS",
                }

            # --- 2. Quantity Variance ---
            inv_qty = inv_line.get("quantity")
            po_qty = po_line.get("quantity")

            if inv_qty is not None and po_qty is not None and po_qty > 0:
                qty_variance_pct = abs(inv_qty - po_qty) / po_qty

                if inv_qty > po_qty * (1 + ctx.qty_tolerance_pct):
                    has_flag = True
                    findings.append(
                        f"Line {inv_line_num}: quantity over-invoiced "
                        f"(inv: {inv_qty} vs PO: {po_qty})"
                    )
                elif qty_variance_pct > ctx.qty_tolerance_pct:
                    has_flag = True
                    findings.append(
                        f"Line {inv_line_num}: quantity variance {qty_variance_pct:.1%}"
                    )

    # --- 3. Header Total Alignment ---
    if ctx.total_amount is not None and ctx.po_total > 0:
        header_variance_pct = abs(ctx.total_amount - ctx.po_total) / ctx.po_total
        inputs["invoice_total"] = ctx.total_amount
        inputs["po_total"] = ctx.po_total
        calculations["header_variance_pct"] = round(header_variance_pct, 4)

        if header_variance_pct > ctx.price_tolerance_pct * 2:  # 2x tolerance for header
            has_flag = True
            findings.append(
                f"Header total variance: {header_variance_pct:.1%} "
                f"(inv: ${ctx.total_amount:,.2f} vs PO: ${ctx.po_total:,.2f})"
            )

    # --- 4. PO Balance Check ---
    if ctx.total_amount is not None:
        inputs["po_remaining"] = ctx.po_remaining
        if ctx.total_amount > ctx.po_remaining:
            overage = ctx.total_amount - ctx.po_remaining
            has_flag = True
            findings.append(
                f"Invoice ${ctx.total_amount:,.2f} exceeds PO remaining "
                f"${ctx.po_remaining:,.2f} by ${overage:,.2f}"
            )
            calculations["po_balance_overage"] = round(overage, 2)

    # --- Determine status ---
    if has_failure:
        status = "FAIL"
        reason = "PRICE_VARIANCE_EXCEEDED"
        severity = "HIGH"
    elif has_flag:
        status = "FLAG"
        reason = "AMOUNT_VARIANCE_DETECTED"
        severity = "MEDIUM"
    else:
        status = "PASS"
        reason = ""
        severity = "LOW"
        if not findings:
            findings.append("All amount checks passed")

    return ValidationCheck(
        check_id="amount_variance",
        status=status,
        reason_code=reason,
        severity=severity,
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        inputs=inputs,
        calculation=calculations,
        evidence=findings,
        evidence_refs=[ctx.po_ref] if ctx.po_ref else [],
    )


def _get_invoice_line(lines: list[dict], line_num: int) -> dict | None:
    """Get invoice line by 1-indexed number."""
    if 0 < line_num <= len(lines):
        return lines[line_num - 1]
    return None


def _get_po_line(po_lines: list[dict], line_num: int) -> dict | None:
    """Get PO line by line_number field."""
    for pl in po_lines:
        if pl.get("line_number") == line_num:
            return pl
    return None
