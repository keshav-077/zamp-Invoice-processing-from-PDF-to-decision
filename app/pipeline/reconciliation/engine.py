"""
InvoiceFlow AI — Reconciliation Engine

Flexible total reconciliation supporting extra charges, inferred residuals,
and configurable outcomes for Stage 1 routing.
"""

import logging
from decimal import Decimal, InvalidOperation

from app.config import settings
from app.models.extraction import InvoiceExtraction
from app.models.reconciliation import ReconciliationCheck, ReconciliationResult
from app.pipeline.policy_loader import load_routing_policy

logger = logging.getLogger(__name__)


class ReconciliationEngine:
    """Reconcile extracted invoice amounts against total."""

    def __init__(self, tolerance: float | None = None):
        self.tolerance = Decimal(str(tolerance or settings.arithmetic_tolerance))
        self.policy = load_routing_policy()
        self.residual_threshold = Decimal(
            str(self.policy.get("residual_review_threshold", 50.0))
        )

    def reconcile(self, extraction: InvoiceExtraction) -> ReconciliationResult:
        checks: list[ReconciliationCheck] = []
        inferred_charges: list[dict] = []

        subtotal = self._to_decimal(extraction.subtotal.value)
        tax = self._to_decimal(extraction.tax_amount.value)
        total = self._to_decimal(extraction.total_amount.value)

        charge_sum = Decimal("0")
        discount_sum = Decimal("0")
        for charge in extraction.extra_charges:
            amt = self._to_decimal(charge.amount)
            if amt is None:
                continue
            if charge.category == "discount" or amt < 0:
                discount_sum += abs(amt)
            else:
                charge_sum += amt

        line_sum = Decimal("0")
        for item in extraction.line_items:
            amt = self._to_decimal(item.amount)
            if amt is not None:
                line_sum += amt

        if line_sum > 0 and subtotal is not None:
            checks.append(self._compare("line_items_sum_equals_subtotal", line_sum, subtotal))

        if subtotal is None or tax is None or total is None:
            missing = []
            if subtotal is None:
                missing.append("subtotal")
            if tax is None:
                missing.append("tax_amount")
            if total is None:
                missing.append("total_amount")
            checks.append(ReconciliationCheck(
                check_name="primary_total_reconciliation",
                status="skipped",
                detail=f"Missing fields: {', '.join(missing)}",
            ))
            return ReconciliationResult(overall_status="partial", checks=checks)

        base = subtotal + tax + charge_sum - discount_sum
        residual = total - base

        if self._match(base, total):
            checks.append(ReconciliationCheck(
                check_name="primary_total_reconciliation",
                expected=float(base),
                actual=float(total),
                status="pass",
                detail=f"{subtotal} + {tax} + charges({charge_sum}) - discounts({discount_sum}) = {total} ✓",
            ))
            overall = "reconciled_with_inferred_charges" if extraction.extra_charges else "reconciled"
            return ReconciliationResult(overall_status=overall, checks=checks)

        if charge_sum == 0 and abs(residual) > self.tolerance:
            inferred_charges.append({
                "label": "Unexplained residual",
                "category": "other",
                "amount": float(residual),
                "inferred": True,
            })
            adjusted = subtotal + tax + residual
            if self._match(adjusted, total):
                checks.append(ReconciliationCheck(
                    check_name="residual_inferred_charge",
                    expected=float(adjusted),
                    actual=float(total),
                    status="review",
                    detail=(
                        f"Residual {float(residual):.2f} inferred as fee "
                        f"(likely shipping/handling) — {subtotal} + {tax} + {residual} = {total}"
                    ),
                ))
                overall = (
                    "residual_review"
                    if abs(residual) >= self.residual_threshold
                    else "reconciled_with_inferred_charges"
                )
                return ReconciliationResult(
                    overall_status=overall,
                    checks=checks,
                    inferred_charges=inferred_charges,
                    residual_amount=float(residual),
                )

        checks.append(ReconciliationCheck(
            check_name="primary_total_reconciliation",
            expected=float(base),
            actual=float(total),
            status="fail",
            detail=f"{subtotal} + {tax} + charges = {base} ≠ {total} (residual: {float(residual):.2f})",
        ))

        checks.extend(self._line_item_checks(extraction))
        checks.extend(self._sanity_checks(extraction))

        return ReconciliationResult(
            overall_status="failed",
            checks=checks,
            residual_amount=float(residual),
        )

    def _line_item_checks(self, extraction: InvoiceExtraction) -> list[ReconciliationCheck]:
        checks = []
        for i, item in enumerate(extraction.line_items, 1):
            qty = self._to_decimal(item.quantity)
            price = self._to_decimal(item.unit_price)
            amount = self._to_decimal(item.amount)
            if qty is None or price is None or amount is None:
                continue
            expected = qty * price
            if self._match(expected, amount):
                checks.append(ReconciliationCheck(
                    check_name=f"line_item_{i}_amount",
                    expected=float(expected),
                    actual=float(amount),
                    status="pass",
                    detail=f"Line {i}: {qty} × {price} = {amount} ✓",
                ))
            else:
                checks.append(ReconciliationCheck(
                    check_name=f"line_item_{i}_amount",
                    expected=float(expected),
                    actual=float(amount),
                    status="fail",
                    detail=f"Line {i}: {qty} × {price} ≠ {amount}",
                ))
        return checks

    def _sanity_checks(self, extraction: InvoiceExtraction) -> list[ReconciliationCheck]:
        checks = []
        total = self._to_decimal(extraction.total_amount.value)
        tax = self._to_decimal(extraction.tax_amount.value)
        if total and total > 0:
            checks.append(ReconciliationCheck(
                check_name="positive_total",
                actual=float(total),
                status="pass",
                detail=f"Total {total} > 0 ✓",
            ))
        if tax is not None and total is not None and tax <= total:
            checks.append(ReconciliationCheck(
                check_name="tax_not_exceeds_total",
                status="pass",
                detail=f"Tax {tax} ≤ Total {total} ✓",
            ))
        return checks

    def _compare(self, name: str, expected: Decimal, actual: Decimal) -> ReconciliationCheck:
        if self._match(expected, actual):
            return ReconciliationCheck(
                check_name=name,
                expected=float(expected),
                actual=float(actual),
                status="pass",
                detail=f"{expected} ≈ {actual} ✓",
            )
        return ReconciliationCheck(
            check_name=name,
            expected=float(expected),
            actual=float(actual),
            status="fail",
            detail=f"{expected} ≠ {actual}",
        )

    def _to_decimal(self, value) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _match(self, a: Decimal, b: Decimal) -> bool:
        return abs(a - b) <= self.tolerance

    def to_arithmetic_result(self, reconciliation: ReconciliationResult):
        """Backward-compatible conversion for existing consumers."""
        from app.models.arithmetic import ArithmeticCheck, ArithmeticResult

        status_map = {
            "pass": "pass",
            "fail": "fail",
            "skipped": "skipped",
            "review": "pass",
        }
        checks = [
            ArithmeticCheck(
                check_name=c.check_name,
                expected=c.expected,
                actual=c.actual,
                status=status_map.get(c.status, "skipped"),
                detail=c.detail,
            )
            for c in reconciliation.checks
        ]

        if reconciliation.overall_status == "failed":
            overall = "fail"
        elif reconciliation.overall_status in ("reconciled", "reconciled_with_inferred_charges"):
            overall = "pass"
        else:
            overall = "partial"

        return ArithmeticResult(overall_status=overall, checks=checks)
